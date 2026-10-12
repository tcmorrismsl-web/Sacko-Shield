#!/usr/bin/env python3
"""Sacko Shield frequent refresh — runs on GitHub Actions.

Writes overlay.json: NFL-wide data only (no league, team or manager names), so
it is safe in a public repo. The page fetches it on open and every 15 minutes,
and lays it over the data baked into index.html:

  week, kickoffs   current week by the schedule rule, real UTC kickoffs
  proj             Sleeper's projected stat lines for the week, by Sleeper id
  status           injury designation (+ practice/news fields when Sleeper sends them)
  weather          per team: kickoff-window forecast, roof, and stat multipliers
  experts          FantasyPros weekly consensus (rank, change, grade, projection)
  trending         Sleeper adds/drops over the last 24 hours

Also writes diag.json: what every source returned (keys, counts, errors), so a
run can be checked instead of trusted.

Cadence: the workflow fires every 15 minutes; this script decides whether a run
is due and exits early (writing nothing) when it is not:
  * within 2 hours before any kickoff of the week  -> every 15 min
  * while any game is in progress                  -> every 30 min
  * otherwise                                      -> every 120 min
Pass --force to run regardless.

Standard library only, so the workflow needs no installs.
"""
import argparse, csv, io, json, math, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stadiums import STADIUMS  # noqa: E402

UA = "SackoShield/1.0 (+https://github.com/tcmorrismsl-web/Sacko-Shield)"
GAMES_CSV = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
FP_WEEKLY = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/fp_latest_weekly.csv"
ID_MAP = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
SLEEPER = "https://api.sleeper.app"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
ET = ZoneInfo("America/New_York")
GAME_MIN = 190                      # same game window the page uses

# --- weather multipliers ------------------------------------------------------
# Measured from nflverse 2016-2025 regular-season outdoor team-games, each game
# compared with that team's own season average (leave-one-out). Wind effects
# measured in games above 40F, cold effects in games under 10 mph, so the two
# don't count the same effect twice. Rushing showed no consistent effect and is
# left alone. See docs/weather.md for the table and sample sizes.
WIND = [  # (min mph, yards, tds, receptions, field goals)
    (20, 0.87, 0.91, 0.88, 0.90),
    (15, 0.92, 0.92, 0.96, 0.96),
    (10, 0.96, 0.92, 0.97, 1.00),
]
COLD = [  # (max F, yards, tds, receptions, field goals)
    (25, 0.93, 0.93, 0.92, 0.83),
    (40, 0.95, 1.00, 0.95, 0.90),
]

# Stats kept from Sleeper's projection lines. Anything a league could score;
# scoreLine() ignores keys a league doesn't pay for.
DROP_PREFIX = ("pts_", "adp_", "pos_adp", "rank", "pos_rank", "gp", "gs", "tm_", "cmp_pct")
POSITIONS = ["QB", "RB", "WR", "TE", "K"]


# The page's team codes (LAR, JAX, ...). nflverse writes LA, FantasyPros JAC.
TEAM_ALIAS = {"LA": "LAR", "JAC": "JAX", "WSH": "WAS", "LVR": "LV", "OAK": "LV",
              "SD": "LAC", "STL": "LAR"}


def team(code):
    return TEAM_ALIAS.get(code, code)


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url, diag, label, as_json=True, timeout=30):
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            diag["sources"][label] = {"url": url, "status": r.status, "bytes": len(body),
                                      "ms": int((time.time() - t0) * 1000)}
            return json.loads(body) if as_json else body.decode("utf-8")
    except Exception as e:  # noqa: BLE001 — recorded, never swallowed silently
        diag["sources"][label] = {"url": url, "error": f"{type(e).__name__}: {e}"}
        return None


# --- schedule -------------------------------------------------------------------
def load_schedule(diag):
    text = get(GAMES_CSV, diag, "nflverse_games", as_json=False, timeout=60)
    if not text:
        raise SystemExit("games.csv unavailable; nothing written")
    rows = list(csv.DictReader(io.StringIO(text)))
    season = max(int(r["season"]) for r in rows)
    reg = [r for r in rows if int(r["season"]) == season and r["game_type"] == "REG"]
    games = []
    for r in reg:
        kick_et = datetime.strptime(f'{r["gameday"]} {r["gametime"]}', "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        kick = kick_et.astimezone(timezone.utc)
        games.append({
            "week": int(r["week"]), "kick": kick, "end": kick + timedelta(minutes=GAME_MIN),
            "home": team(r["home_team"]), "away": team(r["away_team"]), "stadium_id": r["stadium_id"],
            "final": r["home_score"] not in ("", "NA"),
            "spread": r["spread_line"], "total": r["total_line"],
        })
    # the rule from current-week.md: the earliest week with any game lacking a final
    open_weeks = sorted({g["week"] for g in games if not g["final"]})
    week = open_weeks[0] if open_weeks else max(g["week"] for g in games)
    return season, week, games


def implied(g):
    """Each side's implied points from the line (home = total/2 + spread/2, as
    in the main build; nflverse's spread_line is positive when home is favoured)."""
    try:
        sp, tot = float(g["spread"]), float(g["total"])
    except (TypeError, ValueError):
        return None, None
    return round(tot / 2 + sp / 2, 2), round(tot / 2 - sp / 2, 2)


def kickoff_table(games, week):
    out = {}
    for g in games:
        if g["week"] != week:
            continue
        h_imp, a_imp = implied(g)
        for team, opp, home, imp in ((g["home"], g["away"], True, h_imp),
                                     (g["away"], g["home"], False, a_imp)):
            out[team] = {"kick": iso(g["kick"]), "end": iso(g["end"]), "final": g["final"],
                         "opp": opp, "home": home, "implied": imp}
    return out


def due(games, week, prev, now, force):
    """Return (is_due, interval_minutes, reason)."""
    wk = [g for g in games if g["week"] == week]
    running = any(g["kick"] <= now < g["end"] for g in wk)
    soon = any(g["kick"] - timedelta(hours=2) <= now < g["kick"] for g in wk)
    interval = 15 if soon else 30 if running else 120
    reason = "pre-kickoff window" if soon else "games in progress" if running else "quiet"
    if force:
        return True, interval, reason + " (forced)"
    try:
        last = datetime.fromisoformat(prev["generated_at"].replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001 — no previous overlay means run now
        return True, interval, reason + " (no previous overlay)"
    if prev.get("week") != week:
        return True, interval, reason + " (week changed)"
    # 3 minutes of slack: GitHub's scheduler runs late, never early
    return (now - last) >= timedelta(minutes=interval - 3), interval, reason


# --- Sleeper ----------------------------------------------------------------------
def sleeper_state(diag):
    return get(f"{SLEEPER}/v1/state/nfl", diag, "sleeper_state") or {}


def clean_stats(stats, pos):
    out = {}
    for k, v in (stats or {}).items():
        if not isinstance(v, (int, float)) or v == 0 or k.startswith(DROP_PREFIX):
            continue
        out[k] = round(float(v), 3)
    if pos == "K":
        if "fgmiss" not in out and "fga" in out:
            out["fgmiss"] = round(max(0.0, out["fga"] - out.get("fgm", 0.0)), 3)
        if "xpmiss" not in out and "xpa" in out:
            out["xpmiss"] = round(max(0.0, out["xpa"] - out.get("xpm", 0.0)), 3)
    return out


STATUS_KEYS = ("injury_status", "injury_body_part", "injury_notes", "injury_start_date",
               "practice_participation", "practice_description", "status", "news_updated")


def sleeper_projections(season, week, diag):
    proj, status, ok_positions = {}, {}, []
    key_union, player_key_union = set(), set()
    for pos in POSITIONS:
        q = urllib.parse.urlencode({"season_type": "regular", "position[]": pos, "order_by": "pts_ppr"})
        rows = get(f"{SLEEPER}/projections/nfl/{season}/{week}?{q}", diag, f"sleeper_proj_{pos}")
        if not isinstance(rows, list):
            continue
        kept = 0
        for r in rows:
            key_union.update(r.keys())
            pid = str(r.get("player_id") or "")
            pl = r.get("player") or {}
            player_key_union.update(pl.keys())
            line = clean_stats(r.get("stats"), pos)
            if pid and line:
                proj[pid] = {"s": line, "t": team(r.get("team") or pl.get("team") or "")}
                kept += 1
            # only players with a designation; news_updated alone is everyone
            if pid and pl.get("injury_status"):
                status[pid] = {k: pl.get(k) for k in STATUS_KEYS if pl.get(k) not in (None, "", [])}
        diag["sources"][f"sleeper_proj_{pos}"]["kept"] = kept
        if kept:
            ok_positions.append(pos)
    diag["sleeper_projection_keys"] = sorted(key_union)
    diag["sleeper_projection_player_keys"] = sorted(player_key_union)
    diag["status_fields_seen"] = sorted({k for s in status.values() for k in s})
    return proj, status, ok_positions


def sleeper_trending(diag):
    out = {}
    for kind in ("add", "drop"):
        rows = get(f"{SLEEPER}/v1/players/nfl/trending/{kind}?lookback_hours=24&limit=40",
                   diag, f"sleeper_trending_{kind}")
        if isinstance(rows, list):
            out[kind] = [[str(r.get("player_id")), r.get("count")] for r in rows if r.get("player_id")]
    return out


# --- official injury report: practice participation -----------------------------
INJURIES = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"
PRACTICE = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "Limited",
            "Full Participation in Practice": "Full"}


def practice_report(season, week, id_text, status, diag):
    """Merge the week's practice participation and game designation into status.

    nflverse's injuries file carries one row per player per week: the latest
    practice status that week and the report's game designation (Out,
    Doubtful, Questionable). Matched to Sleeper ids through gsis_id."""
    text = get(INJURIES.format(season=season), diag, "nflverse_injuries", as_json=False, timeout=60)
    if not text or not id_text:
        return
    gsis2sl = {}
    for r in csv.DictReader(io.StringIO(id_text)):
        if r.get("gsis_id") not in (None, "", "NA") and r.get("sleeper_id") not in (None, "", "NA"):
            gsis2sl[r["gsis_id"]] = r["sleeper_id"]
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r.get("week") == str(week)]
    matched = 0
    for r in rows:
        sid = gsis2sl.get(r["gsis_id"])
        prac = PRACTICE.get(r.get("practice_status", ""))
        if not sid or (not prac and not r.get("report_status")):
            continue
        matched += 1
        e = status.setdefault(sid, {})
        if prac:
            e["practice"] = prac
            if r.get("practice_primary_injury"):
                e["practice_injury"] = r["practice_primary_injury"]
        if r.get("report_status"):
            e["report_status"] = r["report_status"]
    diag["practice_report"] = {"rows_this_week": len(rows), "matched": matched}


# --- weather ----------------------------------------------------------------------
def wx_multipliers(wind, temp):
    m = {"yd": 1.0, "td": 1.0, "rec": 1.0, "fg": 1.0}
    for lo, yd, td, rec, fg in WIND:
        if wind is not None and wind >= lo:
            m = {"yd": m["yd"] * yd, "td": m["td"] * td, "rec": m["rec"] * rec, "fg": m["fg"] * fg}
            break
    for hi, yd, td, rec, fg in COLD:
        if temp is not None and temp <= hi:
            m = {"yd": m["yd"] * yd, "td": m["td"] * td, "rec": m["rec"] * rec, "fg": m["fg"] * fg}
            break
    return {k: round(v, 3) for k, v in m.items()}


def game_weather(g, diag):
    st = STADIUMS.get(g["stadium_id"])
    base = {"stadium_id": g["stadium_id"], "kick": iso(g["kick"])}
    if not st:
        diag.setdefault("unknown_stadiums", []).append(g["stadium_id"])
        return {**base, "roof": "unknown", "note": "stadium not in table; no weather"}
    name, lat, lon, roof = st
    base.update({"stadium": name, "roof": roof})
    if roof == "dome":
        return base
    day0 = g["kick"].date().isoformat()
    day1 = g["end"].date().isoformat()
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "UTC",
        "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,snowfall",
        "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
        "start_date": day0, "end_date": day1,
    })
    data = get(f"{OPEN_METEO}?{q}", diag, f"weather_{g['home']}")
    h = (data or {}).get("hourly")
    if not h:
        return {**base, "note": "forecast unavailable"}
    # hours that overlap the game window
    idx = [i for i, t in enumerate(h["time"])
           if g["kick"] - timedelta(minutes=59) <= datetime.fromisoformat(t).replace(tzinfo=timezone.utc) < g["end"]]
    if not idx:
        return {**base, "note": "kickoff beyond forecast range"}
    pick = lambda k: [h[k][i] for i in idx if h[k][i] is not None]  # noqa: E731
    mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    wind, temp = mean(pick("wind_speed_10m")), mean(pick("temperature_2m"))
    gust = max(pick("wind_gusts_10m") or [0]) or None
    precip = round(sum(pick("precipitation")), 2)
    pprob = max(pick("precipitation_probability") or [0])
    snow = round(sum(pick("snowfall")), 2)
    flags = []
    if wind is not None and wind >= 15:
        flags.append(f"wind {wind:.0f} mph")
    if temp is not None and temp <= 32:
        flags.append(f"{temp:.0f}°F")
    if snow >= 0.2:
        flags.append("snow")
    elif pprob >= 50 and precip >= 0.1:
        flags.append("rain")
    out = {**base, "temp_f": temp, "wind_mph": wind, "gust_mph": gust, "precip_in": precip,
           "precip_prob": pprob, "snow_in": snow, "flags": flags,
           "hours": len(idx), "forecast_at": iso(now_utc())}
    # a retractable roof is open or closed on game day, so no adjustment
    if roof == "outdoor":
        out["mult"] = wx_multipliers(wind, temp)
    return out


def name_key(name):
    """Lower case, no punctuation, no generational suffix: 'Kenneth Walker III' -> 'kenneth walker'."""
    import re
    k = re.sub(r"[^a-z ]", "", name.lower().replace(".", "").replace("'", "").replace("-", " "))
    k = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", k.strip())
    return re.sub(r"\s+", " ", k)


# --- FantasyPros weekly consensus -------------------------------------------------
def experts(season, week, games, prev, diag):
    text = get(FP_WEEKLY, diag, "fp_weekly", as_json=False)
    ids = get(ID_MAP, diag, "id_map", as_json=False, timeout=60)
    if not text or not ids:
        return {}, None, ids
    fp2sl = {}
    for r in csv.DictReader(io.StringIO(ids)):
        if r.get("fantasypros_id") and r.get("sleeper_id") not in (None, "", "NA"):
            fp2sl[r["fantasypros_id"]] = r["sleeper_id"]
    rows = list(csv.DictReader(io.StringIO(text)))
    # Does the scrape cover this week? Match stated opponents against the schedule.
    wk_pairs = set()
    for g in games:
        if g["week"] == week:
            wk_pairs |= {(g["home"], g["away"]), (g["away"], g["home"])}
    stated = [(team(r["team"]), team(r["player_opponent_id"])) for r in rows
              if r.get("player_opponent_id") not in (None, "", "NA") and r["team"] != "FA"]
    matched = sum(1 for p in stated if p in wk_pairs)
    covers = bool(stated) and matched / len(stated) >= 0.9
    diag["fp_weekly_coverage"] = {"rows": len(rows), "with_opponent": len(stated),
                                  "match_this_week": matched, "covers_week": covers,
                                  "scrape_date": rows[0].get("scrape_date") if rows else None}
    if not covers:
        return {}, rows[0].get("scrape_date") if rows else None, ids
    prev_ex = prev.get("experts", {}) if prev.get("week") == week else {}
    out, unmapped = {}, 0
    num = lambda v: float(v) if v not in (None, "", "NA") else None  # noqa: E731
    for r in rows:
        if r["pos"] not in ("QB", "RB", "WR", "TE", "K", "DST"):
            continue                              # IDP: no league here uses it
        if r["pos"] == "DST":
            sid = team(r["team"])                 # the page keys defenses by team
        else:
            sid = fp2sl.get(r["fantasypros_id"])
        if not sid:
            # not in the id map (mostly rookie kickers): the page matches these
            # on its own normalised name key plus position
            sid = "nm:" + name_key(r["player_name"]) + "|" + r["pos"]
            unmapped += 1
        ecr = num(r["ecr"])
        first = (prev_ex.get(sid) or {}).get("ecr_first", ecr)
        out[sid] = {"ecr": ecr, "pos_rank": r.get("pos_rank"), "grade": r.get("start_sit_grade"),
                    "proj": num(r.get("r2p_pts")), "delta": num(r.get("player_ecr_delta")),
                    "ecr_first": first}
    diag["fp_weekly_coverage"]["unmapped"] = unmapped
    return out, rows[0].get("scrape_date") if rows else None, ids


# --- CORS probe: can the GitHub page itself call these hosts? -----------------------
def cors_probe(diag, origin="https://tcmorrismsl-web.github.io"):
    probes = {
        "sleeper": f"{SLEEPER}/v1/state/nfl",
        "espn_fantasy": "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leagues/0?view=mStatus",
        "raw_github": "https://raw.githubusercontent.com/tcmorrismsl-web/Sacko-Shield/main/README.md",
    }
    out = {}
    for name, url in probes.items():
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Origin": origin})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out[name] = {"status": r.status, "acao": r.headers.get("Access-Control-Allow-Origin"),
                             "acac": r.headers.get("Access-Control-Allow-Credentials")}
        except urllib.error.HTTPError as e:
            out[name] = {"status": e.code, "acao": e.headers.get("Access-Control-Allow-Origin"),
                         "acac": e.headers.get("Access-Control-Allow-Credentials")}
        except Exception as e:  # noqa: BLE001
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    diag["cors"] = out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev", default="prev/overlay.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    now = now_utc()
    diag = {"started_at": iso(now), "sources": {}}
    try:
        prev = json.load(open(a.prev))
    except Exception:  # noqa: BLE001
        prev = {}

    season, week, games = load_schedule(diag)
    ok, interval, reason = due(games, week, prev, now, a.force)
    diag.update({"season": season, "week_games_csv": week, "due": ok,
                 "interval_min": interval, "reason": reason})
    os.makedirs(a.out, exist_ok=True)
    if not ok:
        print(f"not due ({reason}; every {interval} min) — nothing written")
        return

    state = sleeper_state(diag)
    sl_week = state.get("display_week") or state.get("week")
    diag["week_sleeper"] = sl_week

    proj, status, proj_positions = sleeper_projections(season, week, diag)
    trending = sleeper_trending(diag)
    weather = {}
    for g in games:
        if g["week"] == week and not g["final"]:
            w = game_weather(g, diag)
            weather[g["home"]] = w
            weather[g["away"]] = w
    ex, fp_date, id_text = experts(season, week, games, prev, diag)
    practice_report(season, week, id_text, status, diag)
    cors_probe(diag)

    overlay = {
        "v": 1, "generated_at": iso(now_utc()), "season": season, "week": week,
        "week_source": {"games_csv": week, "sleeper": sl_week,
                        "rule": "earliest week with any game lacking a final score"},
        "cadence": {"interval_min": interval, "reason": reason},
        "kickoffs": kickoff_table(games, week),
        "proj": proj, "proj_positions": proj_positions, "status": status, "weather": weather,
        "experts": ex, "experts_scraped": fp_date, "trending": trending,
    }
    # the last 40 publish times, so the real cadence can be audited later
    overlay["history"] = (prev.get("history") or [])[-39:] + [overlay["generated_at"]]
    # sanity gate: never publish an overlay that would blank the app
    if len(proj) < 150:
        diag["published"] = False
        diag["refused"] = f"only {len(proj)} projection lines; previous overlay kept"
        json.dump(diag, open(os.path.join(a.out, "diag.json"), "w"), indent=1)
        print(diag["refused"])
        return
    diag["published"] = True
    diag["counts"] = {"proj": len(proj), "status": len(status), "weather_teams": len(weather),
                      "experts": len(ex), "trending_add": len(trending.get("add", []))}
    json.dump(overlay, open(os.path.join(a.out, "overlay.json"), "w"), separators=(",", ":"))
    json.dump(diag, open(os.path.join(a.out, "diag.json"), "w"), indent=1)
    print(json.dumps(diag["counts"]), reason)


if __name__ == "__main__":
    main()
