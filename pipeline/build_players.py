#!/usr/bin/env python3
"""Sacko Shield — build the normalized player dataset from public sources."""
import json, math, re, unicodedata
import pandas as pd
import numpy as np

D = "/home/claude/data"
OUT = "/home/claude/app/data"
FANTASY_POS = {"QB", "RB", "WR", "TE", "K", "DST", "DEF", "PK"}

def norm_name(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

TEAM_FIX = {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV",
            "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU",
            # MFL / DynastyProcess three-letter codes
            "KCC": "KC", "NEP": "NE", "LVR": "LV", "SFO": "SF", "GBP": "GB",
            "NOS": "NO", "TBB": "TB", "RAM": "LAR", "SDC": "LAC", "OAK": "LV",
            "WAS": "WAS", "JAG": "JAX"}

def fix_team(t):
    if not isinstance(t, str):
        return None
    t = t.strip().upper()
    return TEAM_FIX.get(t, t)

def sid(v):
    """Sleeper ids come through as floats; emit clean strings."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        s = str(v).strip()
        return s or None

def nn(v):
    """JSON-safe scalar."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if math.isnan(f) else round(f, 3)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if pd.isna(v) if not isinstance(v, (list, dict, str)) else False:
        return None
    return v

# ---------------------------------------------------------------- identities
ids = pd.read_csv(f"{D}/db_playerids.csv", low_memory=False)
ids = ids[ids.db_season == ids.db_season.max()]
ids = ids[ids.position.isin(FANTASY_POS)]
ids["key"] = ids.name.map(norm_name)
ids = ids.drop_duplicates("key", keep="first")

# ------------------------------------------------------------------- rosters
ros = pd.read_csv(f"{D}/roster.csv", low_memory=False)
ros = ros.sort_values("week").groupby("gsis_id", as_index=False).last()
ros["key"] = ros.full_name.map(norm_name)
ros = ros.drop_duplicates("key", keep="last")

# ------------------------------------------------------------- dynasty value
val = pd.read_csv(f"{D}/values.csv")
val["key"] = val.player.map(norm_name)
val = val.drop_duplicates("key", keep="first")
VALUE_ASOF = str(val.scrape_date.max())

# --------------------------------------------------------------- ECR (multi)
ecr = pd.read_csv(f"{D}/fp_ecr.csv", low_memory=False)
ecr["key"] = ecr.player.map(norm_name)
ECR_ASOF = str(ecr.scrape_date.max())

def ecr_slice(page, col):
    s = ecr[ecr.fp_page == page].drop_duplicates("key", keep="first")
    return s.set_index("key")[["ecr", "sd", "best", "worst", "rank_delta", "bye"]].rename(
        columns={"ecr": col})

dsf = ecr_slice("/nfl/rankings/dynasty-superflex.php", "ecr_dyn_sf")["ecr_dyn_sf"]
dov = ecr_slice("/nfl/rankings/dynasty-overall.php", "ecr_dyn_1qb")["ecr_dyn_1qb"]
rook = ecr_slice("/nfl/rankings/rookies.php", "ecr_rookie")["ecr_rookie"]
ros_pages = ["/nfl/rankings/ros-qb.php", "/nfl/rankings/ros-ppr-rb.php",
             "/nfl/rankings/ros-ppr-wr.php", "/nfl/rankings/ros-ppr-te.php",
             "/nfl/rankings/ros-k.php", "/nfl/rankings/ros-dst.php"]
rospos = ecr[ecr.fp_page.isin(ros_pages)].drop_duplicates("key", keep="first")
ros_ecr = rospos.set_index("key")["ecr"]
ros_bye = rospos.set_index("key")["bye"]
ros_own = rospos.set_index("key")["player_owned_avg"]
ros_overall = ecr[ecr.fp_page == "/nfl/rankings/ros-ppr-overall.php"].drop_duplicates(
    "key", keep="first").set_index("key")["ecr"]

# ----------------------------------------------------------- weekly rankings
wk = pd.read_csv(f"{D}/fp_weekly.csv", low_memory=False)
wk["key"] = wk.player_name.map(norm_name)
wk = wk.drop_duplicates("key", keep="first").set_index("key")
WEEKLY_ASOF = str(wk.scrape_date.max())

# ------------------------------------------------------------- season stats
st = pd.read_csv(f"{D}/stats_week.csv", low_memory=False)
MAX_WEEK = int(st.week.max())
keep = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
        "carries", "rushing_yards", "rushing_tds", "receptions", "targets",
        "receiving_yards", "receiving_tds", "fantasy_points_ppr", "target_share",
        "air_yards_share", "wopr"]
st["key"] = st.player_display_name.map(norm_name)
agg = st.groupby("key").agg(
    games=("week", "nunique"),
    **{c: (c, "sum") for c in keep if c not in ("target_share", "air_yards_share", "wopr")},
    target_share=("target_share", "mean"),
    air_yards_share=("air_yards_share", "mean"),
    wopr=("wopr", "mean"),
)
agg["ppg"] = agg.fantasy_points_ppr / agg.games.replace(0, np.nan)
# weekly fantasy point log for consistency / boom-bust
wkpts = (st.pivot_table(index="key", columns="week", values="fantasy_points_ppr",
                        aggfunc="sum").fillna(0))
# which weeks each player actually appeared in, so a filled zero isn't mistaken
# for a zero-point performance
played_weeks = st.groupby("key")["week"].apply(lambda x: set(int(w) for w in x)).to_dict()

# -------------------------------------------------------------------- snaps
sn = pd.read_csv(f"{D}/snaps.csv")
sn["key"] = sn.player.map(norm_name)
snap = sn.groupby("key").agg(snap_pct=("offense_pct", "mean"),
                             snap_pct_last=("offense_pct", "last")).mul(1)

# ----------------------------------------------------------------- injuries
inj = pd.read_csv(f"{D}/injuries.csv")
inj_week = int(inj.week.max())
inj = inj[inj.week == inj_week]
inj["key"] = inj.full_name.map(norm_name)
inj = inj.drop_duplicates("key", keep="last").set_index("key")

# ----------------------------------------------------------------- schedule
g = pd.read_csv(f"{D}/games.csv", low_memory=False)
g26 = g[g.season == 2026].copy()
g26["home_team"] = g26.home_team.map(fix_team)
g26["away_team"] = g26.away_team.map(fix_team)
UPCOMING_WEEK = int(g26[g26.home_score.isna()].week.min())

sched = {}
byes = {}
teams = sorted(set(g26.home_team) | set(g26.away_team))
for t in teams:
    rows = []
    for _, r in g26[(g26.home_team == t) | (g26.away_team == t)].sort_values("week").iterrows():
        home = r.home_team == t
        rows.append({"w": int(r.week), "opp": r.away_team if home else r.home_team,
                     "home": bool(home),
                     "pf": nn(r.home_score if home else r.away_score),
                     "pa": nn(r.away_score if home else r.home_score),
                     "spread": nn(r.spread_line if "spread_line" in r else None),
                     "total": nn(r.total_line if "total_line" in r else None)})
    sched[t] = rows
    played = {x["w"] for x in rows}
    byes[t] = [w for w in range(1, 19) if w not in played]

# team defense strength: fantasy points allowed to each position, season to date
st_pos = st[st.position.isin(["QB", "RB", "WR", "TE"])].copy()
st_pos["opponent_team"] = st_pos.opponent_team.map(fix_team)
dvp = (st_pos.groupby(["opponent_team", "position"])["fantasy_points_ppr"]
       .sum().unstack(fill_value=0))
gp = st_pos.groupby("opponent_team")["week"].nunique()
dvp = dvp.div(gp, axis=0)
dvp_rank = dvp.rank(ascending=False)   # 1 = most generous defense

# ------------------------------------------------------------------ assemble
base = ids.merge(ros[["key", "team", "status", "years_exp", "depth_chart_position",
                      "headshot_url", "espn_id", "sleeper_id", "gsis_id"]],
                 on="key", how="outer", suffixes=("", "_r"))
base["team"] = base.team.fillna(base.team_r) if "team_r" in base else base.team
base = base[base.key.astype(bool)]

players = []
for _, r in base.iterrows():
    k = r.key
    pos = r.position if isinstance(r.position, str) else None
    if pos in (None, "DEF", "PK"):
        pos = {"DEF": "DST", "PK": "K"}.get(pos, pos)
    team = r.get("team") or r.get("team_r")
    v = val.set_index("key")["value_2qb"].get(k) if k in set(val.key) else None
    vrow = val[val.key == k]
    a = agg.loc[k] if k in agg.index else None
    w = wk.loc[k] if k in wk.index else None
    ir = inj.loc[k] if k in inj.index else None
    sp = snap.loc[k] if k in snap.index else None
    # Only weeks he actually has a stat line: a pivot fills absences with 0,
    # and a zero he was never on the field for is not a zero-point game.
    logs, logw = [], []
    if k in wkpts.index:
        row = wkpts.loc[k]
        for wknum in wkpts.columns:
            if k in played_weeks and int(wknum) in played_weeks[k]:
                logs.append(nn(row[wknum]))
                logw.append(int(wknum))

    has_signal = any([
        k in val.key.values, k in agg.index, k in wk.index,
        k in dsf.index, k in ros_ecr.index,
    ])
    if not has_signal:
        continue
    if pos not in {"QB", "RB", "WR", "TE", "K", "DST"}:
        continue

    sl = sid(r.get("sleeper_id")) or sid(r.get("sleeper_id_r"))
    team = fix_team(team)
    p = {
        "id": sl or ("k_" + k.replace(" ", "_")),
        "key": k,
        "name": r.get("name") if isinstance(r.get("name"), str) else (
            vrow.player.iloc[0] if len(vrow) else k.title()),
        "pos": pos,
        "team": team if isinstance(team, str) else "FA",
        "age": nn(r.get("age")) or (nn(vrow.age.iloc[0]) if len(vrow) else None),
        "exp": nn(r.get("years_exp")),
        "draft_year": nn(r.get("draft_year")),
        "espn": sid(r.get("espn_id")),
        "sleeper": sl,
        "status": r.get("status") if isinstance(r.get("status"), str) else None,
        # values
        "v_sf": nn(vrow.value_2qb.iloc[0]) if len(vrow) else None,
        "v_1qb": nn(vrow.value_1qb.iloc[0]) if len(vrow) else None,
        "ecr_dyn_sf": nn(dsf.get(k)),
        "ecr_dyn_1qb": nn(dov.get(k)),
        "ecr_rookie": nn(rook.get(k)),
        "ecr_ros": nn(ros_ecr.get(k)),
        "ecr_ros_overall": nn(ros_overall.get(k)),
        "own": nn(ros_own.get(k)),
        "bye": nn(ros_bye.get(k)) or (byes.get(team, [None])[0] if isinstance(team, str) else None),
        # weekly
        "wk_ecr": nn(w.ecr) if w is not None else None,
        "wk_pos_rank": (w.pos_rank if w is not None and isinstance(w.pos_rank, str) else None),
        "wk_proj": nn(w.r2p_pts) if w is not None else None,
        "wk_grade": (w.start_sit_grade if w is not None and isinstance(w.start_sit_grade, str) else None),
        "wk_opp": (w.player_opponent if w is not None and isinstance(w.player_opponent, str) else None),
        "wk_sd": nn(w.sd) if w is not None else None,
        # production
        "g": nn(a.games) if a is not None else 0,
        "pts": nn(a.fantasy_points_ppr) if a is not None else None,
        "ppg": nn(a.ppg) if a is not None else None,
        "logs": logs,
        "logw": logw,
        "tgt": nn(a.targets) if a is not None else None,
        "rec": nn(a.receptions) if a is not None else None,
        "recyd": nn(a.receiving_yards) if a is not None else None,
        "rectd": nn(a.receiving_tds) if a is not None else None,
        "car": nn(a.carries) if a is not None else None,
        "ruyd": nn(a.rushing_yards) if a is not None else None,
        "rutd": nn(a.rushing_tds) if a is not None else None,
        "payd": nn(a.passing_yards) if a is not None else None,
        "patd": nn(a.passing_tds) if a is not None else None,
        "int": nn(a.passing_interceptions) if a is not None else None,
        "tgt_share": nn(a.target_share * 100) if a is not None and pd.notna(a.target_share) else None,
        "wopr": nn(a.wopr) if a is not None else None,
        "snap": nn(sp.snap_pct * 100) if sp is not None and pd.notna(sp.snap_pct) else None,
        "snap_last": nn(sp.snap_pct_last * 100) if sp is not None and pd.notna(sp.snap_pct_last) else None,
        # injury
        "inj": (ir.report_status if ir is not None and isinstance(ir.report_status, str) else None),
        "inj_note": (ir.report_primary_injury if ir is not None and isinstance(ir.report_primary_injury, str) else None),
        "inj_week": int(inj_week) if ir is not None else None,
    }
    players.append(p)

# ------------------------------------------------- team defenses (DST rows)
TEAM_BY_NAME = {}
for t in teams:
    TEAM_BY_NAME[norm_name(t)] = t
NICK = {"cardinals": "ARI", "falcons": "ATL", "ravens": "BAL", "bills": "BUF",
        "panthers": "CAR", "bears": "CHI", "bengals": "CIN", "browns": "CLE",
        "cowboys": "DAL", "broncos": "DEN", "lions": "DET", "packers": "GB",
        "texans": "HOU", "colts": "IND", "jaguars": "JAX", "chiefs": "KC",
        "raiders": "LV", "chargers": "LAC", "rams": "LAR", "dolphins": "MIA",
        "vikings": "MIN", "patriots": "NE", "saints": "NO", "giants": "NYG",
        "jets": "NYJ", "eagles": "PHI", "steelers": "PIT", "seahawks": "SEA",
        "49ers": "SF", "niners": "SF", "buccaneers": "TB", "titans": "TEN",
        "commanders": "WAS"}

def team_from_label(s):
    if not isinstance(s, str):
        return None
    low = s.lower()
    for nick, abbr in NICK.items():
        if nick in low:
            return abbr
    return fix_team(s.split()[-1]) if s else None

dst_wk = pd.read_csv(f"{D}/fp_weekly.csv", low_memory=False)
dst_wk = dst_wk[dst_wk.page == "dst"]
dst_ros = ecr[ecr.fp_page == "/nfl/rankings/ros-dst.php"]
dst_dyn = ecr[ecr.fp_page == "/nfl/rankings/dynasty-dst.php"]
ros_by_team = {team_from_label(r.player): r for _, r in dst_ros.iterrows()}
dyn_by_team = {team_from_label(r.player): r for _, r in dst_dyn.iterrows()}

for _, r in dst_wk.iterrows():
    t = fix_team(r.team) or team_from_label(r.player_name)
    if not t:
        continue
    rr, dd = ros_by_team.get(t), dyn_by_team.get(t)
    players.append({
        "id": t, "key": f"dst {t.lower()}", "name": f"{t} D/ST", "pos": "DST",
        "team": t, "age": None, "exp": None, "draft_year": None,
        "espn": None, "sleeper": t, "status": "ACT",
        "v_sf": None, "v_1qb": None, "ecr_dyn_sf": None,
        "ecr_dyn_1qb": nn(dd.ecr) if dd is not None else None,
        "ecr_rookie": None,
        "ecr_ros": nn(rr.ecr) if rr is not None else None,
        "ecr_ros_overall": None,
        "own": nn(rr.player_owned_avg) if rr is not None else None,
        "bye": (byes.get(t) or [None])[0],
        "wk_ecr": nn(r.ecr), "wk_pos_rank": r.pos_rank if isinstance(r.pos_rank, str) else None,
        "wk_proj": nn(r.r2p_pts),
        "wk_grade": r.start_sit_grade if isinstance(r.start_sit_grade, str) else None,
        "wk_opp": r.player_opponent if isinstance(r.player_opponent, str) else None,
        "wk_sd": nn(r.sd),
        "g": 0, "pts": None, "ppg": None, "logs": [],
        "tgt": None, "rec": None, "recyd": None, "rectd": None, "car": None,
        "ruyd": None, "rutd": None, "payd": None, "patd": None, "int": None,
        "tgt_share": None, "wopr": None, "snap": None, "snap_last": None,
        "inj": None, "inj_note": None,
    })

# ------------------------------------------------ transparent own projection
# "Sacko projection". The points-per-positional-rank curve is not invented:
# it is measured from FantasyPros' own weekly projected points, so the output
# lands on the same scale real projections use. A player's rest-of-season
# consensus rank places him on that curve; recent production, the opponent's
# fantasy points allowed and the injury report move him along it.
POS_CURVE = {}
wk_raw = pd.read_csv(f"{D}/fp_weekly.csv", low_memory=False)
for pos in ["QB", "RB", "WR", "TE", "K", "DST"]:
    pts = (wk_raw[wk_raw.page_pos == pos]["r2p_pts"].dropna()
           .sort_values(ascending=False).to_numpy())
    if len(pts) < 8:
        continue
    # light smoothing so a single noisy projection doesn't dent the curve
    POS_CURVE[pos] = pd.Series(pts).rolling(5, center=True, min_periods=1).mean().to_numpy()

def curve_points(pos, rank):
    """Projected points for the Nth-best player at a position."""
    c = POS_CURVE.get(pos)
    if c is None or rank is None:
        return None
    if rank <= len(c):
        return float(c[int(rank) - 1])
    # past the ranked pool, decay toward zero rather than cutting off
    tail = float(c[-1])
    return max(0.0, tail * math.exp(-0.08 * (rank - len(c))))

pos_ros_rank = {}
for pos in POS_CURVE:
    grp = sorted([p for p in players if p["pos"] == pos and p["ecr_ros"] is not None],
                 key=lambda x: x["ecr_ros"])
    for i, p in enumerate(grp, 1):
        pos_ros_rank[p["key"]] = i

# replacement level: the starter-count-th best player at each position across
# a 12-team league, used later for waiver value over replacement
REPLACEMENT = {pos: curve_points(pos, n) for pos, n in
               [("QB", 20), ("RB", 30), ("WR", 40), ("TE", 14), ("K", 12), ("DST", 12)]}

for p in players:
    rank = pos_ros_rank.get(p["key"])
    base = curve_points(p["pos"], rank)
    if base is None and p["ppg"]:
        base = p["ppg"] * 0.85
    if base is None:
        p["proj"] = None
        p["proj_parts"] = None
        continue
    # recent form: pull the consensus baseline toward what he has actually done
    form = 1.0
    if p["ppg"] and p["g"]:
        ratio = p["ppg"] / base if base > 0 else 1.0
        form = 1 + 0.35 * (min(max(ratio, 0.35), 2.6) - 1)
    # matchup: opponent's rank in fantasy points allowed to the position
    matchup, opp = 1.0, None
    nxt = next((x for x in sched.get(p["team"] or "", []) if x["w"] == UPCOMING_WEEK), None)
    if nxt:
        opp = nxt["opp"]
        rk = (dvp_rank.loc[opp, p["pos"]]
              if opp in dvp_rank.index and p["pos"] in dvp_rank.columns else None)
        if rk and not pd.isna(rk):
            matchup = 1 + 0.12 * ((16.5 - float(rk)) / 15.5)
    # availability
    # Injury reports here are from the LAST completed week, so they are a
    # signal, not a verdict — never zero a starter out on stale information.
    # The UI shows the flag and the report week alongside the number.
    avail = {"Out": 0.15, "Doubtful": 0.45, "Questionable": 0.92}.get(p["inj"], 1.0)
    if not nxt:
        avail = 0.0   # genuinely on bye / no game this week
    proj = base * form * matchup * avail
    p["proj"] = round(proj, 2)
    p["opp"] = opp
    p["home"] = nxt["home"] if nxt else None
    p["proj_parts"] = {"base": round(base, 2), "form": round(form, 3),
                       "matchup": round(matchup, 3), "avail": avail,
                       "ros_pos_rank": rank}
    # points above replacement — the only fair way to compare a TE to a WR
    repl = REPLACEMENT.get(p["pos"])
    p["par"] = round(proj - repl, 2) if repl is not None else None

# de-dup on sleeper id / key
seen, final = set(), []
for p in sorted(players, key=lambda x: -(x["v_sf"] or 0)):
    if p["key"] in seen:
        continue
    seen.add(p["key"])
    final.append(p)

# Which week do the FantasyPros weekly rankings actually cover? Infer it by
# matching their stated opponents against the real schedule, rather than
# trusting the scrape date — the file can lag a week.
votes = {}
for _, row in wk.reset_index().iterrows():
    t, opp_s = fix_team(row.get("team")), row.get("player_opponent")
    if not t or not isinstance(opp_s, str):
        continue
    opp = fix_team(opp_s.replace("vs.", "").replace("at", "").strip())
    for game in sched.get(t, []):
        if game["opp"] == opp:
            votes[game["w"]] = votes.get(game["w"], 0) + 1
WEEKLY_WEEK = max(votes, key=votes.get) if votes else None

meta = {
    "built": pd.Timestamp.utcnow().isoformat(),
    "weekly_covers_week": WEEKLY_WEEK,
    "replacement": {k: (round(v, 2) if v is not None else None)
                    for k, v in REPLACEMENT.items()},
    "season": 2026,
    "completed_week": MAX_WEEK,
    "upcoming_week": UPCOMING_WEEK,
    "sources": {
        "dynasty_values": VALUE_ASOF,
        "ecr": ECR_ASOF,
        "weekly_ecr": WEEKLY_ASOF,
        "stats_through_week": MAX_WEEK,
        "injuries_week": inj_week,
    },
}

import os
os.makedirs(OUT, exist_ok=True)
json.dump(final, open(f"{OUT}/players.json", "w"), separators=(",", ":"), allow_nan=False)
json.dump({"sched": sched, "byes": byes,
           "dvp": {t: {p: nn(dvp_rank.loc[t, p]) for p in dvp_rank.columns if t in dvp_rank.index}
                   for t in teams if t in dvp_rank.index},
           "dvp_pts": {t: {p: nn(dvp.loc[t, p]) for p in dvp.columns if t in dvp.index}
                       for t in teams if t in dvp.index}},
          open(f"{OUT}/schedule.json", "w"), separators=(",", ":"))

# Picks are priced by DynastyProcess in ECR-rank terms, not on the player
# value scale, so interpolate each pick's rank against the player value curve.
picks = pd.read_csv(f"{D}/values-picks.csv")

def rank_curve(rank_col, value_col):
    c = val[[rank_col, value_col]].dropna().sort_values(rank_col)
    return c[rank_col].to_numpy(), c[value_col].to_numpy()

sf_r, sf_v = rank_curve("ecr_2qb", "value_2qb")
qb_r, qb_v = rank_curve("ecr_1qb", "value_1qb")

def rank_to_value(rank, xs, ys):
    if rank is None or pd.isna(rank):
        return None
    return float(np.interp(float(rank), xs, ys))

pick_rows = []
for _, r in picks.iterrows():
    label = r.player if isinstance(r.player, str) else None
    if not label or pd.isna(r.ecr_2qb):
        continue
    pick_rows.append({
        "pick": label.replace("Pick ", ""),
        "pos": "PICK",
        "v_sf": nn(round(rank_to_value(r.ecr_2qb, sf_r, sf_v))),
        "v_1qb": nn(round(rank_to_value(r.ecr_1qb, qb_r, qb_v))),
    })
json.dump(pick_rows, open(f"{OUT}/picks.json", "w"),
          separators=(",", ":"), allow_nan=False)
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)
print("picks:", len(pick_rows), "e.g.", [p["pick"] for p in pick_rows[:6]])

print(json.dumps(meta, indent=1))
print("players:", len(final))
print("with dynasty SF value:", sum(1 for p in final if p["v_sf"]))
print("with weekly proj:", sum(1 for p in final if p["wk_proj"]))
print("with season stats:", sum(1 for p in final if p["g"]))
print("by pos:", pd.Series([p["pos"] for p in final]).value_counts().to_dict())
for p in final[:5]:
    print(" ", p["name"], p["pos"], p["team"], "SF", p["v_sf"], "ppg", p["ppg"], "sleeper", p["sleeper"])
