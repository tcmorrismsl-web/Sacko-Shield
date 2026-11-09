#!/usr/bin/env python3
"""Sacko Shield base data rebuild — runs on GitHub Actions, no Claude involved.

The page bakes in a "base" data set (app/data/*.json inlined into index.html):
the week, the schedule, the player database, dynasty values, rest-of-season
ranks, season production and the 32 defenses. The 15-minute overlay lays live
projections and injuries over it, but the base itself used to be rebuilt by
hand. This script rebuilds it whenever one of its inputs has changed:

  * the NFL week has turned (games.csv: earliest week with a game not final)
  * nflverse has published another completed week of stats
  * DynastyProcess has re-scraped values or rankings
  * the rebuild logic itself changed (BUILD_VERSION)

It runs as a step of the refresh workflow, straight after overlay.json and
stats.json are written, and reads those two files rather than calling Sleeper
again. It exits 0 with "not due" when nothing changed; on a rebuild it rewrites
app/data/{players,schedule,picks,meta}.json and index.html, and the workflow
commits them to main. Every contract in docs/data-contracts.md is checked
before anything is written; a failed check exits non-zero and writes nothing.

All inputs are NFL-wide public data, so nothing league-specific can enter.
Standard library only.
"""
import argparse, csv, io, json, math, os, pathlib, re, subprocess, sys, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / "overlay"))
from refresh import team, name_key, iso, GAME_MIN, UA  # noqa: E402

BUILD_VERSION = 1            # bump to force one rebuild after changing this file
ET = ZoneInfo("America/New_York")
DP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/"
NV = "https://github.com/nflverse/nflverse-data/releases/download/"
SOURCES = {
    "games.csv": NV + "schedules/games.csv",
    "stats.csv": NV + "stats_player/stats_player_week_{season}.csv",
    "roster.csv": NV + "rosters/roster_{season}.csv",
    "values.csv": DP + "values.csv",
    "values-picks.csv": DP + "values-picks.csv",
    "db_playerids.csv": DP + "db_playerids.csv",
    "db_fpecr_latest.csv": DP + "db_fpecr_latest.csv",
    "fp_latest_weekly.csv": DP + "fp_latest_weekly.csv",
}
OFF = ("QB", "RB", "WR", "TE", "K")
CHECK_EVERY_H = 6            # how often to look for changed inputs between weeks
SHRINK_GAMES = 4             # a team's rates are blended with this many league-average games
MIN_OPPS = 150               # below this a position's own opportunity price is not trusted
PA_BANDS = [(0, 0, "pts_allow_0"), (1, 6, "pts_allow_1_6"), (7, 13, "pts_allow_7_13"),
            (14, 20, "pts_allow_14_20"), (21, 27, "pts_allow_21_27"),
            (28, 34, "pts_allow_28_34"), (35, 999, "pts_allow_35p")]


def r2(x):
    return round(x + 1e-9, 2)


def num(v):
    if v in (None, "", "NA", "NaN"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- scoring table
def default_scoring():
    """The page's own DEFAULT_SCORING, read out of app/index.html so the two
    can never drift: `proj` must be exactly what the page would compute."""
    src = (REPO / "app" / "index.html").read_text()
    m = re.search(r"const DEFAULT_SCORING = \{(.*?)\};", src, re.S)
    if not m:
        raise SystemExit("DEFAULT_SCORING not found in app/index.html")
    body = re.sub(r"//[^\n]*", "", m.group(1))
    sc = {k: float(v) for k, v in re.findall(r"([a-z0-9_]+)\s*:\s*(-?[0-9.]+)", body)}
    if sc.get("pass_td") is None or sc.get("rec") is None or len(sc) < 25:
        raise SystemExit("DEFAULT_SCORING parsed incompletely")
    return sc


def score(line, sc):
    return sum(v * sc[k] for k, v in (line or {}).items() if k in sc)


def pa_key(pa):
    for lo, hi, key in PA_BANDS:
        if lo <= pa <= hi:
            return key
    return PA_BANDS[-1][2]


def expected_pa_points(mu, sc, sd=9.5):
    total = 0.0
    for lo, hi, key in PA_BANDS:
        zl, zh = (lo - 0.5 - mu) / sd, (hi + 0.5 - mu) / sd
        total += 0.5 * (math.erf(zh / math.sqrt(2)) - math.erf(zl / math.sqrt(2))) * sc.get(key, 0)
    return total


# -------------------------------------------------------------------- schedule
def load_games(path):
    rows = read_csv(path)
    season = max(int(r["season"]) for r in rows)
    games = []
    for r in rows:
        if int(r["season"]) != season or r["game_type"] != "REG":
            continue
        kick = datetime.strptime(f'{r["gameday"]} {r["gametime"]}', "%Y-%m-%d %H:%M") \
            .replace(tzinfo=ET).astimezone(timezone.utc)
        games.append({
            "week": int(r["week"]), "kick": kick, "end": kick + timedelta(minutes=GAME_MIN),
            "kick_et_weekday": datetime.strptime(r["gameday"], "%Y-%m-%d").weekday(),
            "home": team(r["home_team"]), "away": team(r["away_team"]),
            "hs": num(r["home_score"]), "as": num(r["away_score"]),
            "final": r["home_score"] not in ("", "NA"),
            "spread": num(r["spread_line"]), "total": num(r["total_line"]),
        })
    open_weeks = sorted({g["week"] for g in games if not g["final"]})
    week = open_weeks[0] if open_weeks else max(g["week"] for g in games)
    return season, week, games


def build_schedule(games, week, dvp, dvp_pts):
    teams = sorted({g["home"] for g in games} | {g["away"] for g in games})
    last = max(g["week"] for g in games)
    sched = {t: [] for t in teams}
    kick = {}
    for g in sorted(games, key=lambda g: (g["week"], g["kick"])):
        for t, opp, home, pf, pa in ((g["home"], g["away"], True, g["hs"], g["as"]),
                                     (g["away"], g["home"], False, g["as"], g["hs"])):
            # nflverse's spread_line as it stands: positive when the HOME side is favoured
            sched[t].append({"w": g["week"], "opp": opp, "home": home, "pf": pf, "pa": pa,
                             "spread": g["spread"], "total": g["total"]})
            kick.setdefault(str(g["week"]), {})[t] = {
                "kick": iso(g["kick"]), "end": iso(g["end"]), "final": g["final"],
                "opp": opp, "home": home}
    byes = {t: [w for w in range(1, last + 1) if w not in {e["w"] for e in sched[t]}]
            for t in teams}
    return {"sched": sched, "byes": byes, "dvp": dvp, "dvp_pts": dvp_pts, "kickoffs": kick}


def check_kickoffs(games):
    """current-week.md: a Thursday-ET game must land on Friday UTC, and nothing
    kicks off in the Thursday UTC daytime except Thanksgiving."""
    bad = []
    for g in games:
        if g["kick_et_weekday"] == 3:                       # Thursday in Eastern time
            thanksgiving = g["kick"].month == 11 and 22 <= g["kick"].day <= 28
            if g["kick"].weekday() != 4 and not thanksgiving:
                bad.append(f'week {g["week"]} {g["away"]}@{g["home"]} {iso(g["kick"])}')
    return bad


# ----------------------------------------------------- defenses, from nflverse
def defenses(stats, games, through, sc):
    """Season lines for the 32 defenses, from what each team's DEFENCE did
    (dst-correction.md), cross-checked against what opposing offences gave up."""
    played = {}                                   # (team, week) -> points allowed
    for g in games:
        if g["final"] and g["week"] <= through:
            played[(g["home"], g["week"])] = int(g["as"])
            played[(g["away"], g["week"])] = int(g["hs"])
    f = lambda r, k: num(r.get(k)) or 0.0  # noqa: E731
    made, gave = {}, {}
    for r in stats:
        wk = int(r["week"])
        t, o = team(r["team"]), team(r["opponent_team"])
        if wk > through or (t, wk) not in played:
            continue
        d = made.setdefault((t, wk), {"sack": 0.0, "int": 0.0, "fum_rec": 0.0, "def_td": 0.0,
                                      "st_td": 0.0, "safe": 0.0, "blk_kick": 0.0})
        d["sack"] += f(r, "def_sacks")
        d["int"] += f(r, "def_interceptions")
        d["fum_rec"] += f(r, "fumble_recovery_opp")
        d["def_td"] += f(r, "def_tds") + f(r, "fumble_recovery_tds")
        d["st_td"] += f(r, "special_teams_tds")
        d["safe"] += f(r, "def_safeties")
        d["blk_kick"] += f(r, "def_punt_blocks") + f(r, "def_pat_blocks") + f(r, "def_fg_blocks")
        v = gave.setdefault((o, wk), [0.0, 0.0])              # keyed by the DEFENCE facing them
        v[0] += f(r, "sacks_suffered")
        v[1] += f(r, "passing_interceptions")
    # the two-sided check: a defence's sacks and picks must match what the
    # opposing offences suffered, within one event per team-week
    off_by = [k for k in made if k in gave
              and (abs(made[k]["sack"] - gave[k][0]) > 1.01 or abs(made[k]["int"] - gave[k][1]) > 1.01)]
    if len(off_by) > 6:
        raise SystemExit(f"defense two-sided check failed for {len(off_by)} team-weeks: {off_by[:6]}")

    out, tot = {}, {"g": 0, "sack": 0.0, "ta": 0.0, "td": 0.0, "blk": 0.0, "safe": 0.0, "int": 0.0}
    for (t, wk), pa in sorted(played.items()):
        if (t, wk) not in made:
            continue                              # nflverse hasn't published that week yet
        line = {k: v for k, v in made[(t, wk)].items() if v}
        e = out.setdefault(t, {"logw": [], "wstats": [], "pa_log": [], "logs": []})
        w = dict(line)
        w[pa_key(pa)] = 1.0
        e["logw"].append(wk); e["wstats"].append(w); e["pa_log"].append(pa)
        e["logs"].append(r2(score(w, sc)))
        tot["g"] += 1
        tot["sack"] += line.get("sack", 0); tot["int"] += line.get("int", 0)
        tot["ta"] += line.get("int", 0) + line.get("fum_rec", 0)
        tot["td"] += line.get("def_td", 0) + line.get("st_td", 0)
        tot["blk"] += line.get("blk_kick", 0); tot["safe"] += line.get("safe", 0)
    n = max(1, tot["g"])
    league = {"sack": tot["sack"] / n, "ta": tot["ta"] / n, "td": tot["td"] / n,
              "blk": tot["blk"] / n, "safe": tot["safe"] / n,
              "int_share": tot["int"] / tot["ta"] if tot["ta"] else 0.55}
    return out, league, len(off_by)


def dvp_tables(stats, through):
    """Fantasy points each defense has allowed to each position, and its rank
    per game played (1 = most allowed), so a team that has had its bye is not
    ranked as stingier than it is."""
    pts, wks = {}, {}
    for r in stats:
        if int(r["week"]) > through or r["position"] not in ("QB", "RB", "WR", "TE"):
            continue
        t = team(r["opponent_team"])
        d = pts.setdefault(t, {"QB": 0.0, "RB": 0.0, "TE": 0.0, "WR": 0.0})
        d[r["position"]] += num(r.get("fantasy_points_ppr")) or 0.0
        wks.setdefault(t, set()).add(int(r["week"]))
    rank = {t: {} for t in pts}
    for pos in ("QB", "RB", "TE", "WR"):
        for i, t in enumerate(sorted(pts, key=lambda t: -pts[t][pos] / len(wks[t]))):
            rank[t][pos] = float(i + 1)
    return rank, {t: {p: r2(v) for p, v in d.items()} for t, d in pts.items()}


# ------------------------------------------------------------------- the build
def build(src, app, overlay, stats_feed, now):
    sc = default_scoring()
    sc_log = dict(sc, st_td=6.0)                  # a return touchdown counts in the weekly log
    season, week, games = load_games(src / "games.csv")
    bad = check_kickoffs(games)
    if bad:
        raise SystemExit("kickoff conversion check failed: " + "; ".join(bad[:4]))
    if int(overlay.get("week") or 0) != week or int(overlay.get("season") or 0) != season:
        raise SystemExit(f"overlay is for week {overlay.get('week')}, schedule says {week}; not rebuilding")
    proj = overlay.get("proj") or {}
    if len(proj) < 150:
        raise SystemExit(f"only {len(proj)} projected stat lines in the overlay; not rebuilding")
    done = {}
    for g in games:
        done.setdefault(g["week"], []).append(g["final"])
    completed = max([w for w, f in done.items() if w < week and all(f)] or [0])

    nfl = [r for r in read_csv(src / "stats.csv") if r.get("season_type", "REG") == "REG"]
    nfl_weeks = sorted({int(r["week"]) for r in nfl})
    nfl_through = min(completed, max(nfl_weeks or [0]))

    old = json.loads((app / "data" / "players.json").read_text())
    old_meta = json.loads((app / "data" / "meta.json").read_text())
    template = [k for k in next(p for p in old if p["pos"] == "WR")]
    by_id = {str(p["id"]): p for p in old}

    # ---- identity: nflverse roster, then DynastyProcess ids
    roster = {r["sleeper_id"]: r for r in read_csv(src / "roster.csv")
              if r.get("sleeper_id") not in (None, "", "NA")}
    ids = read_csv(src / "db_playerids.csv")
    fp2sl = {r["fantasypros_id"]: r["sleeper_id"] for r in ids
             if r.get("fantasypros_id") not in (None, "", "NA")
             and r.get("sleeper_id") not in (None, "", "NA")}
    id_row = {r["sleeper_id"]: r for r in ids if r.get("sleeper_id") not in (None, "", "NA")}

    def new_row(sid):
        ro, dr = roster.get(sid), id_row.get(sid)
        pos = (ro or {}).get("position") or (dr or {}).get("position")
        name = (ro or {}).get("full_name") or (dr or {}).get("name")
        if pos == "FB":
            pos = "RB"
        if pos not in OFF or not name:
            return None
        p = {k: None for k in template}
        p.update({"id": sid, "sleeper": sid, "key": name_key(name), "name": name, "pos": pos,
                  "team": "FA", "espn": (ro or {}).get("espn_id") or (dr or {}).get("espn_id") or None})
        dy = num((ro or {}).get("rookie_year")) or num((dr or {}).get("draft_year"))
        p["draft_year"] = dy
        return p

    weeks_feed = {int(w): rows for w, rows in (stats_feed.get("weeks") or {}).items()}
    wanted = set(proj) | {sid for rows in weeks_feed.values() for sid in rows}
    created = []
    for sid in sorted(wanted):
        if sid not in by_id and sid.isdigit():
            p = new_row(sid)
            if p:
                by_id[sid] = p
                created.append(p["name"])
    players = list(by_id.values())

    sched_teams = {g["home"] for g in games} | {g["away"] for g in games}
    this_week = {}
    for g in games:
        if g["week"] == week:
            this_week[g["home"]] = (g["away"], True, g)
            this_week[g["away"]] = (g["home"], False, g)
    bye_of = {t: [w for w in range(1, 19) if not any(
        g["week"] == w and t in (g["home"], g["away"]) for g in games)] for t in sched_teams}

    for p in players:
        if p["pos"] == "DST":
            continue
        ro = roster.get(str(p.get("sleeper") or ""))
        if ro:
            p["status"] = ro.get("status") or p.get("status")
            p["depth"] = ro.get("depth_chart_position") or p.get("depth")
            p["exp"] = num(ro.get("years_exp")) if num(ro.get("years_exp")) is not None else p.get("exp")
            p["espn"] = p.get("espn") or (ro.get("espn_id") if ro.get("espn_id") not in ("", "NA") else None)
            t = team(ro.get("team") or "")
            if ro.get("status") in ("CUT", "RET") or t not in sched_teams:
                t = "FA"
            p["team"] = t
            bd = ro.get("birth_date")
            if bd and bd != "NA":
                try:
                    p["age"] = round((now.date() - datetime.strptime(bd, "%Y-%m-%d").date()).days / 365.25, 1)
                except ValueError:
                    pass
        # Sleeper's own team for anyone it projects is the freshest read
        t = (proj.get(str(p["id"])) or {}).get("t")
        if t in sched_teams:
            p["team"] = t
        if p.get("team") not in sched_teams:
            p["team"] = "FA"

    # ---- values and rankings (DynastyProcess / FantasyPros)
    by_key = {}
    for p in players:
        by_key.setdefault((p["key"], p["pos"]), p)
    def find(fp_id, name, pos, tm=None):
        if pos in ("DST", "DEF"):
            return by_id.get(team(tm or ""))
        sid = fp2sl.get(str(fp_id))
        if sid and sid in by_id:
            return by_id[sid]
        return by_key.get((name_key(name), pos))

    for p in players:
        for k in ("v_sf", "v_1qb", "ecr_dyn_sf", "ecr_dyn_1qb", "ecr_rookie", "ecr_ros",
                  "ecr_ros_overall", "wk_ecr", "wk_pos_rank", "wk_proj", "wk_grade", "wk_opp", "wk_sd"):
            p[k] = None
    values = read_csv(src / "values.csv")
    for r in values:
        p = find(r["fp_id"], r["player"], r["pos"])
        if p:
            p["v_sf"], p["v_1qb"] = int(num(r["value_2qb"]) or 0), int(num(r["value_1qb"]) or 0)
            if p.get("age") is None:
                p["age"] = num(r["age"])
    ecr = read_csv(src / "db_fpecr_latest.csv")
    FIELD = {"dsf": "ecr_dyn_sf", "do": "ecr_dyn_1qb", "drk": "ecr_rookie", "rp": "ecr_ros",
             "ro": "ecr_ros_overall"}
    for r in ecr:
        pos = r["pos"]
        if pos not in OFF + ("DST",):
            continue
        p = find(r["id"], r["player"], pos, r.get("tm") or r.get("team"))
        if not p:
            continue
        field = FIELD.get(r["ecr_type"])
        if pos == "DST":                          # defenses: positional pages only
            field = {"dp": "ecr_dyn_1qb", "rp": "ecr_ros"}.get(r["ecr_type"])
        if field and num(r["ecr"]) is not None:
            p[field] = num(r["ecr"])
        if num(r.get("player_owned_avg")) is not None:
            p["own"] = num(r["player_owned_avg"])

    # ---- weekly consensus, only when it actually covers this week
    wk_rows = read_csv(src / "fp_latest_weekly.csv")
    pairs = {(t, o) for t, (o, _, _) in this_week.items()}
    stated = [(team(r["team"]), team(r["player_opponent_id"])) for r in wk_rows
              if r.get("player_opponent_id") not in (None, "", "NA") and r["team"] != "FA"]
    covers = bool(stated) and sum(1 for s in stated if s in pairs) / len(stated) >= 0.9
    if covers:
        for r in wk_rows:
            if r["pos"] not in OFF + ("DST",) or r["page_pos"] != r["pos"]:
                continue
            p = find(r["fantasypros_id"], r["player_name"], r["pos"], r["team"])
            if p:
                p.update({"wk_ecr": num(r["ecr"]), "wk_pos_rank": r["pos_rank"] or None,
                          "wk_proj": num(r["r2p_pts"]), "wk_sd": num(r["sd"]),
                          "wk_grade": r["start_sit_grade"] if r["start_sit_grade"] not in ("", "NA") else None,
                          "wk_opp": r["player_opponent"] if r["player_opponent"] not in ("", "NA") else None})

    # ---- season production: Sleeper's real stat lines (the same feed the page reads)
    pos_of = {str(p.get("sleeper") or p["id"]): p["pos"] for p in players}
    agg = {pos: {"car": 0.0, "tgt": 0.0, "att": 0.0, "rush": 0.0, "recv": 0.0, "pass": 0.0, "rec": 0.0}
           for pos in ("QB", "RB", "WR", "TE")}
    for rows in weeks_feed.values():
        for sid, l in rows.items():
            a = agg.get(pos_of.get(sid))
            if a is None:
                continue
            g = lambda k: l.get(k, 0.0)  # noqa: E731
            a["car"] += g("rush_att"); a["tgt"] += g("rec_tgt"); a["att"] += g("pass_att")
            a["rush"] += 0.1 * g("rush_yd") + 6 * g("rush_td")
            a["recv"] += 0.1 * g("rec_yd") + 6 * g("rec_td") + g("rec")
            a["pass"] += 0.04 * g("pass_yd") + 4 * g("pass_td") - 2 * g("pass_int")
            a["rec"] += g("rec")
    allp = {k: sum(a[k] for a in agg.values()) for k in next(iter(agg.values()))}
    rate = lambda a, n, d: (a[n] / a[d]) if a[d] >= MIN_OPPS else (allp[n] / allp[d] if allp[d] else 0.0)  # noqa: E731
    rates, guarded = {}, []
    for pos, a in agg.items():
        rates[pos] = {"per_carry": round(rate(a, "rush", "car"), 4),
                      "per_target": round(rate(a, "recv", "tgt"), 4),
                      "per_attempt": round(rate(a, "pass", "att"), 4),
                      "catch_rate": round(rate(a, "rec", "tgt"), 4)}
        guarded += [f"{pos}.{n} ({int(a[d])} opportunities < {MIN_OPPS})"
                    for n, d in (("per_carry", "car"), ("per_target", "tgt"), ("per_attempt", "att"))
                    if a[d] < MIN_OPPS]

    feed_weeks = sorted(weeks_feed)
    for p in players:
        if p["pos"] == "DST":
            continue
        sid = str(p.get("sleeper") or p["id"])
        wk = [w for w in feed_weeks if sid in weeks_feed[w]]
        lines = [weeks_feed[w][sid] for w in wk]
        tot = {}
        for l in lines:
            for k, v in l.items():
                tot[k] = tot.get(k, 0.0) + v
        n = lambda k: tot.get(k, 0.0)  # noqa: E731
        pooled = {k: r2(v) for k, v in tot.items() if not k.startswith("_")}
        p["g"] = len(lines)
        p["logw"] = wk
        p["logs"] = [r2(score(l, sc)) for l in lines]
        p["sstats"] = pooled
        p["pts"] = r2(score(pooled, sc)) if lines else None
        p["ppg"] = r2(p["pts"] / p["g"]) if lines else None
        p.update({"tgt": n("rec_tgt"), "rec": n("rec"), "recyd": n("rec_yd"), "rectd": n("rec_td"),
                  "car": n("rush_att"), "ruyd": n("rush_yd"), "rutd": n("rush_td"),
                  "payd": n("pass_yd"), "patd": n("pass_td"), "int": n("pass_int"), "att": n("pass_att")})
        last_snap = next((l for l in reversed(lines) if l.get("_tsnp")), None)
        p["snap_last"] = round(100 * last_snap.get("_snp", 0) / last_snap["_tsnp"], 1) if last_snap else None
        p["snap"] = round(100 * n("_snp") / n("_tsnp"), 1) if n("_tsnp") else None
        p["tgt_share"] = round(100 * n("rec_tgt") / n("_tt"), 1) if n("_tt") else None
        p["wopr"] = (r2(1.5 * n("rec_tgt") / n("_tt") + 0.7 * n("rec_air_yd") / n("_tay"))
                     if n("_tt") and n("_tay") else (r2(1.5 * n("rec_tgt") / n("_tt")) if n("_tt") else None))
        if p["pos"] == "K":
            p["wstats"] = [{k: v for k, v in l.items() if not k.startswith("_")} for l in lines]
        else:
            p.pop("wstats", None)
        rt = rates.get(p["pos"])
        if rt and lines:
            xfp = p["car"] * rt["per_carry"] + p["tgt"] * rt["per_target"] + p["att"] * rt["per_attempt"]
            p.update({"xfp": r2(xfp), "x_rec": r2(p["tgt"] * rt["catch_rate"]),
                      "poe": r2(p["pts"] - xfp), "poe_g": r2((p["pts"] - xfp) / p["g"]),
                      "opps": int(round(p["car"] + p["tgt"] + p["att"]))})
        else:
            p.update({"xfp": None, "x_rec": None, "poe": None, "poe_g": None, "opps": 0})

        # ---- this week: opponent, and Sleeper's projected stat line
        game = this_week.get(p["team"])
        p["opp"], p["home"] = (game[0], game[1]) if game else (None, None)
        p["bye"] = (bye_of.get(p["team"]) or [None])[0]
        p["inj"] = p["inj_note"] = p["inj_week"] = None        # the overlay supplies these live
        fresh = proj.get(str(p["id"]))
        if game and fresh and fresh.get("s"):
            p["pstats"], p["pstats_src"], p["proj_src"] = dict(fresh["s"]), "sleeper", "sleeper"
        else:
            # no game, or Sleeper projects nothing for him: an empty line, never
            # a stale one (data-contracts.md)
            p["pstats"], p["pstats_src"], p["proj_src"] = {}, None, None
        p["proj"] = r2(score(p["pstats"], sc))
        p["proj_model"], p["par"], p["pstats_shape"], p["proj_parts"] = p["proj"], None, None, None

    # ---- defenses
    dst, league, off_by = defenses(nfl, games, nfl_through, sc_log)
    dvp, dvp_pts = dvp_tables(nfl, nfl_through)
    lines_through = max([g["week"] for g in games if g["spread"] is not None and g["total"] is not None] or [0])
    with_market = 0
    for p in players:
        if p["pos"] != "DST":
            continue
        d = dst.get(p["team"], {"logw": [], "wstats": [], "pa_log": [], "logs": []})
        g = len(d["logw"])
        tot = {}
        for w in d["wstats"]:
            for k, v in w.items():
                if not k.startswith("pts_allow"):
                    tot[k] = tot.get(k, 0.0) + v
        n = lambda k: tot.get(k, 0.0)  # noqa: E731
        ta = n("int") + n("fum_rec")
        p.update({"g": g, "logw": d["logw"], "wstats": d["wstats"], "pa_log": d["pa_log"],
                  "logs": d["logs"], "sstats": {k: r2(v) for k, v in tot.items()},
                  "pts": r2(sum(d["logs"])) if g else None,
                  "ppg": r2(sum(d["logs"]) / g) if g else None,
                  "sacks": n("sack"), "ints": int(n("int")), "fumbles_rec": int(n("fum_rec")),
                  "def_tds": int(n("def_td")), "safeties": int(n("safe")), "blocks": int(n("blk_kick")),
                  "pa_total": sum(d["pa_log"]), "pa_pg": r2(sum(d["pa_log"]) / g) if g else None,
                  "raw_sack_rate": r2(n("sack") / g) if g else None,
                  "raw_ta_rate": r2(ta / g) if g else None,
                  "bye": (bye_of.get(p["team"]) or [None])[0],
                  "inj": None, "inj_note": None, "inj_week": None, "pstats": None, "pstats_src": None})
        shrink = lambda raw, lg: (raw + SHRINK_GAMES * lg) / (g + SHRINK_GAMES)  # noqa: E731
        game = this_week.get(p["team"])
        p["opp"], p["home"] = (game[0], game[1]) if game else (None, None)
        p["dst_ctx"], p["proj"], p["proj_src"] = None, None, None
        if game and game[2]["spread"] is not None and game[2]["total"] is not None:
            gm, home = game[2], game[1]
            opp_implied = gm["total"] / 2 + (-gm["spread"] if home else gm["spread"]) / 2
            ctx = {"opp": game[0], "home": home, "opp_implied": r2(opp_implied), "total": gm["total"],
                   "sack_rate": r2(shrink(n("sack"), league["sack"])),
                   "ta_rate": r2(shrink(ta, league["ta"])),
                   "int_share": r2(n("int") / ta) if ta else r2(league["int_share"]),
                   "dtd_rate": round(shrink(n("def_td") + n("st_td"), league["td"]), 3),
                   "blk_rate": round(shrink(n("blk_kick"), league["blk"]), 3),
                   "safe_rate": round(shrink(n("safe"), league["safe"]), 3), "sd": 9.5}
            # exactly the page's pj() for a defense, under the default table
            p["dst_ctx"] = ctx
            p["proj"] = r2(expected_pa_points(ctx["opp_implied"], sc) + ctx["sack_rate"] * sc["sack"]
                           + ctx["ta_rate"] * (sc["int"] + sc["fum_rec"]) / 2 + 0.06 * sc["def_td"] + 0.35)
            p["proj_src"] = "dst-model"
            with_market += 1
        p["proj_model"], p["par"] = p["proj"], None

    players.sort(key=lambda p: (p["pos"] == "DST", -(p.get("v_sf") or 0), p["name"]))

    # ---- picks
    picks = []
    for r in read_csv(src / "values-picks.csv"):
        val = lambda e: int(round(10500 * math.exp(-0.0235 * e))) if e is not None else None  # noqa: E731
        picks.append({"pick": r["player"].replace(" Pick ", " "), "pos": "PICK",
                      "v_sf": val(num(r["ecr_2qb"])), "v_1qb": val(num(r["ecr_1qb"]))})

    # ---- meta
    n_proj = sum(1 for p in players if p.get("pstats_src") == "sleeper")
    by_pos = {pos: sum(1 for p in players if p["pos"] == pos and p.get("pstats_src") == "sleeper") for pos in OFF}
    feed_through = int(stats_feed.get("through_week") or 0)
    meta = {
        "built": now.isoformat(), "built_by": "github-actions", "build_version": BUILD_VERSION,
        "season": season, "completed_week": completed, "upcoming_week": week, "last_week": 18,
        "weekly_covers_week": week if covers else (week - 1 if stated else None),
        "weekly_trust": covers,
        "sources": {"dynasty_values": values[0]["scrape_date"] if values else None,
                    "ecr": ecr[0]["scrape_date"] if ecr else None,
                    "weekly_ecr": wk_rows[0]["scrape_date"] if wk_rows else None,
                    "stats_through_week": feed_through, "injuries_week": week,
                    "defense_stats_through_week": nfl_through},
        "inputs": fingerprint(src, week, overlay, stats_feed),
        "lines_available_through_week": lines_through,
        "poe": {"method": "opportunity-priced expected points, PPR", "rates": rates,
                "min_opportunities": MIN_OPPS, "guarded": guarded, "through_week": feed_through},
        "dst": {"through_week": nfl_through, "with_market_projection": with_market,
                "two_sided_check_team_weeks_off": off_by,
                "league_rates": {"sacks_per_game": r2(league["sack"]),
                                 "takeaways_per_game": r2(league["ta"]),
                                 "def_tds_per_game": r2(league["td"]),
                                 "int_share_of_takeaways": round(league["int_share"], 3)}},
        "proj_week": week, "proj_source": "Sleeper projected stat lines",
        "stat_line_source": "sleeper",
        "proj_counts": {"sleeper": n_proj, "model": 0}, "proj_counts_by_pos": by_pos,
        "variance": old_meta.get("variance"),
        "created_rows": created,
        "proj_note": (f"Rebuilt automatically for Week {week}. Season production runs through "
                      f"Week {feed_through}; defenses through Week {nfl_through}. "
                      f"{n_proj} players carry a projected stat line; anyone Sleeper does not "
                      f"project shows 0. Injuries, weather and projections keep refreshing on "
                      f"their own between rebuilds."),
    }
    schedule = build_schedule(games, week, dvp, dvp_pts)
    verify(players, schedule, meta, sc, sched_teams, this_week)
    return players, schedule, picks, meta


def verify(players, schedule, meta, sc, sched_teams, this_week):
    """The contracts in docs/data-contracts.md. Any failure stops the build."""
    bad = []
    ids = [p["id"] for p in players]
    if len(set(ids)) != len(ids):
        bad.append("duplicate player ids")
    if len(players) < 600 or sum(1 for p in players if p["pos"] == "DST") != 32:
        bad.append(f"player database too small: {len(players)}")
    for p in players:
        tag = f'{p["name"]} ({p["id"]})'
        if not (len(p["logs"]) == len(p["logw"]) == p["g"]) or p["logw"] != sorted(set(p["logw"])):
            bad.append(f"{tag}: logs/logw/g disagree")
        if "wstats" in p and len(p["wstats"]) != len(p["logw"]):
            bad.append(f"{tag}: wstats length")
        if p["pos"] == "DST":
            c = p.get("dst_ctx")
            if (c is None) != (p["proj"] is None):
                bad.append(f"{tag}: dst_ctx and proj disagree")
            if c and not all(isinstance(c.get(k), (int, float)) for k in ("opp_implied", "sack_rate", "ta_rate")):
                bad.append(f"{tag}: incomplete dst_ctx")
            if p["team"] not in sched_teams:
                bad.append(f"{tag}: unknown team")
            continue
        if p["team"] != "FA" and p["team"] not in sched_teams:
            bad.append(f"{tag}: team {p['team']} not in the schedule")
        if p["team"] not in this_week and p["pstats"]:
            bad.append(f"{tag}: stat line with no game this week")
        if abs((p["proj"] or 0) - score(p["pstats"], sc)) > 0.02:
            bad.append(f"{tag}: proj is not the PPR value of pstats")
        for k in ("value", "dyn_value", "ros_value", "is_dynasty", "format", "league_type", "redraft_value"):
            if k in p:
                bad.append(f"{tag}: format-assuming field {k}")
    if sum(1 for p in players if p.get("pstats_src") == "sleeper") < 150:
        bad.append("fewer than 150 projected stat lines")
    if sum(1 for p in players if p["pos"] != "DST" and p["g"]) < 300:
        bad.append("fewer than 300 players with a game this season")
    if sum(1 for p in players if p.get("v_sf")) < 300 or sum(1 for p in players if p.get("ecr_ros")) < 250:
        bad.append("values or rest-of-season ranks did not attach")
    if len(schedule["kickoffs"].get(str(meta["upcoming_week"]), {})) < 24:
        bad.append("this week's kickoff table is short")
    if bad:
        print(f"REFUSED: {len(bad)} contract failures", file=sys.stderr)
        for b in bad[:25]:
            print("  " + b, file=sys.stderr)
        raise SystemExit(2)


def fingerprint(src, week, overlay, stats_feed):
    """What this build was made from. A rebuild is due when any of it changes."""
    first = lambda f, col: (read_csv(src / f) or [{}])[0].get(col)  # noqa: E731
    with open(src / "stats.csv", newline="", encoding="utf-8") as f:
        team_weeks = {(r["team"], r["week"]) for r in csv.DictReader(f)}
    # team-weeks, not just the latest week: Monday night's two teams land a day late
    return {"build_version": BUILD_VERSION, "week": week,
            "nflverse_team_weeks": len(team_weeks),
            "values": first("values.csv", "scrape_date"),
            "ecr": first("db_fpecr_latest.csv", "scrape_date"),
            "feed_through": int(stats_feed.get("through_week") or 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="base_src", help="folder for the downloaded source files")
    ap.add_argument("--overlay", default="out/overlay.json")
    ap.add_argument("--stats", default="out/stats.json")
    ap.add_argument("--app", default=str(REPO / "app"))
    ap.add_argument("--state-in", default="prev/base_state.json")
    ap.add_argument("--state-out", default="out/base_state.json")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    src, app, now = pathlib.Path(a.src), pathlib.Path(a.app), datetime.now(timezone.utc)
    try:
        state = json.loads(pathlib.Path(a.state_in).read_text())
    except Exception:  # noqa: BLE001 — no state yet
        state = {}
    try:
        overlay = json.loads(pathlib.Path(a.overlay).read_text())
        stats_feed = json.loads(pathlib.Path(a.stats).read_text())
    except Exception as e:  # noqa: BLE001
        print(f"base: overlay or stats feed unreadable ({e}); nothing to do")
        return
    old_meta = json.loads((app / "data" / "meta.json").read_text())
    have = old_meta.get("inputs") or {}

    def save_state(**kw):
        state.update(kw)
        pathlib.Path(a.state_out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.state_out).write_text(json.dumps(state, indent=1))

    # cheap gate first: only download the sources when the week has turned, the
    # build logic changed, or it has been a while since the last look
    try:
        last_check = datetime.fromisoformat(state.get("checked_at", ""))
    except ValueError:
        last_check = None
    week_turned = int(overlay.get("week") or 0) > int(old_meta.get("upcoming_week") or 0)
    feed_moved = int(stats_feed.get("through_week") or 0) > int(have.get("feed_through") or 0)
    stale_look = last_check is None or now - last_check >= timedelta(hours=CHECK_EVERY_H)
    if not (a.force or week_turned or feed_moved or stale_look
            or have.get("build_version") != BUILD_VERSION):
        save_state()
        print("base: not due (week unchanged, inputs checked recently)")
        return

    if not a.no_download:
        src.mkdir(parents=True, exist_ok=True)
        season = int(overlay.get("season") or now.year)
        for name, url in SOURCES.items():
            fetch(url.format(season=season), src / name)
    _, week, _ = load_games(src / "games.csv")
    want = fingerprint(src, week, overlay, stats_feed)
    if want == have and not a.force:
        save_state(checked_at=now.isoformat(), result="inputs unchanged")
        print(f"base: inputs unchanged ({want}); not rebuilding")
        return

    try:
        players, schedule, picks, meta = build(src, app, overlay, stats_feed, now)
    except SystemExit as e:
        save_state(checked_at=now.isoformat(), result=f"refused: {e}")
        raise
    dump = lambda name, obj: (app / "data" / name).write_text(  # noqa: E731
        json.dumps(obj, separators=(",", ":"), allow_nan=False))
    dump("players.json", players); dump("schedule.json", schedule)
    dump("picks.json", picks); dump("meta.json", meta)
    subprocess.run([sys.executable, str(REPO / "pipeline" / "build_standalone.py"),
                    "--app", str(app), "--out", str(REPO / "index.html"), "--public"], check=True)
    save_state(checked_at=now.isoformat(), result="rebuilt", built=now.isoformat(), inputs=want)
    print(f"base: REBUILT for week {week} — {len(players)} players, "
          f"{meta['proj_counts']['sleeper']} projected, inputs {want}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"rebuilt=true\nweek={week}\n")


if __name__ == "__main__":
    main()
