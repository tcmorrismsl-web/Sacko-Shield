#!/usr/bin/env python3
"""Team defenses, scored and projected properly.

D/ST were carrying a rankings-derived number and nothing else — no game log, no
season stats, no way to tell a good matchup from a bad one. This builds them
from the same play-by-play everything else uses:

  * weekly D/ST fantasy points under standard scoring, including the
    points-allowed tiers, from team defensive stats plus the real final scores;
  * a Week N projection driven by the betting market — the opponent's implied
    point total is by far the best single predictor of a defense's week — with
    the team's own sack and takeaway rates shrunk toward league average, because
    two games is not enough to trust a rate.
"""
import json, math
import pandas as pd
import numpy as np

D = "/home/claude/data"
OUT = "/home/claude/app/data"

TEAM_FIX = {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV",
            "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
fix = lambda t: TEAM_FIX.get(str(t).strip().upper(), str(t).strip().upper())

# points-allowed tiers, the near-universal default
PA_TIERS = [(0, 0, 10), (1, 6, 7), (7, 13, 4), (14, 20, 1),
            (21, 27, 0), (28, 34, -1), (35, 99, -4)]

def pa_points(pa):
    for lo, hi, pts in PA_TIERS:
        if lo <= pa <= hi:
            return pts
    return -4

def expected_pa_points(mu, sd=9.5):
    """Tier of the average is not the average of the tiers — a defense facing an
    implied 20 has real chances at both the 7-point and the -1 tier. Integrate."""
    total = 0.0
    for lo, hi, pts in PA_TIERS:
        z_lo = (lo - 0.5 - mu) / sd
        z_hi = (hi + 0.5 - mu) / sd
        p = 0.5 * (math.erf(z_hi / math.sqrt(2)) - math.erf(z_lo / math.sqrt(2)))
        total += p * pts
    return total

# ------------------------------------------------------------ weekly scoring
st = pd.read_csv(f"{D}/stats_week.csv", low_memory=False)
st["team"] = st.team.map(fix)
cols = ["def_sacks", "def_interceptions", "def_tds", "def_safeties",
        "fumble_recovery_opp", "def_fg_blocks", "def_pat_blocks",
        "def_punt_blocks", "special_teams_tds"]
for c in cols:
    st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)
tw = st.groupby(["team", "week"])[cols].sum().reset_index()

g = pd.read_csv(f"{D}/games.csv", low_memory=False)
g26 = g[g.season == 2026].copy()
for c in ("home_team", "away_team"):
    g26[c] = g26[c].map(fix)

# points allowed and opponent, per team-week
pa_rows = []
for _, r in g26.iterrows():
    if pd.notna(r.home_score):
        pa_rows.append({"team": r.home_team, "week": int(r.week),
                        "pa": float(r.away_score), "opp": r.away_team})
        pa_rows.append({"team": r.away_team, "week": int(r.week),
                        "pa": float(r.home_score), "opp": r.home_team})
pa = pd.DataFrame(pa_rows)

tw = tw.merge(pa, on=["team", "week"], how="inner")
tw["blocks"] = tw.def_fg_blocks + tw.def_pat_blocks + tw.def_punt_blocks
tw["takeaways"] = tw.def_interceptions + tw.fumble_recovery_opp
tw["fp"] = (1.0 * tw.def_sacks
            + 2.0 * tw.def_interceptions
            + 2.0 * tw.fumble_recovery_opp
            + 6.0 * (tw.def_tds + tw.special_teams_tds)
            + 2.0 * tw.def_safeties
            + 2.0 * tw.blocks
            + tw.pa.map(pa_points))

COMPLETED = int(tw.week.max())
UPCOMING = int(g26[g26.home_score.isna()].week.min())

season = tw.groupby("team").agg(
    g=("week", "nunique"), fp=("fp", "sum"), sacks=("def_sacks", "sum"),
    ints=("def_interceptions", "sum"), fr=("fumble_recovery_opp", "sum"),
    tds=("def_tds", "sum"), sfty=("def_safeties", "sum"),
    blocks=("blocks", "sum"), pa=("pa", "sum")).reset_index()
season["ppg"] = season.fp / season.g

lg_sack = season.sacks.sum() / season.g.sum()
lg_ta = (season.ints.sum() + season.fr.sum()) / season.g.sum()
lg_td = (season.tds.sum()) / season.g.sum()
K = 4.0   # shrinkage: with 2 games played, lean most of the way on league average

# ------------------------------------------------------- upcoming projection
nxt = g26[g26.week == UPCOMING]
proj, ctx = {}, {}
for _, r in nxt.iterrows():
    tot, spread = r.total_line, r.spread_line
    if pd.isna(tot) or pd.isna(spread):
        continue
    home_implied = tot / 2 + spread / 2
    away_implied = tot / 2 - spread / 2
    for team, opp, opp_implied, home in [
            (r.home_team, r.away_team, away_implied, True),
            (r.away_team, r.home_team, home_implied, False)]:
        s = season[season.team == team]
        gp = float(s.g.iloc[0]) if len(s) else 0
        sack_rate = ((float(s.sacks.iloc[0]) + lg_sack * K) / (gp + K)) if gp else lg_sack
        ta_rate = (((float(s.ints.iloc[0]) + float(s.fr.iloc[0])) + lg_ta * K)
                   / (gp + K)) if gp else lg_ta
        pts = (expected_pa_points(float(opp_implied))
               + 1.0 * sack_rate
               + 2.0 * ta_rate
               + 6.0 * lg_td
               + 0.35)                       # blocks, safeties, return scores
        proj[team] = round(pts, 2)
        ctx[team] = {"opp": opp, "home": bool(home),
                     "opp_implied": round(float(opp_implied), 1),
                     "total": float(tot),
                     "sack_rate": round(sack_rate, 2),
                     "ta_rate": round(ta_rate, 2)}

# ------------------------------------------------------------------- attach
players = json.load(open(f"{OUT}/players.json"))
logs_by_team = {t: grp.sort_values("week") for t, grp in tw.groupby("team")}

hits = 0
for p in players:
    if p["pos"] != "DST":
        continue
    t = p["team"]
    s = season[season.team == t]
    lg_rows = logs_by_team.get(t)
    if lg_rows is not None:
        p["logs"] = [round(float(x), 2) for x in lg_rows.fp.tolist()]
        p["logw"] = [int(x) for x in lg_rows.week.tolist()]
        p["pa_log"] = [int(x) for x in lg_rows.pa.tolist()]
    if len(s):
        row = s.iloc[0]
        p.update({
            "g": int(row.g), "pts": round(float(row.fp), 2),
            "ppg": round(float(row.ppg), 2),
            "sacks": float(row.sacks), "ints": int(row.ints),
            "fumbles_rec": int(row.fr), "def_tds": int(row.tds),
            "safeties": int(row.sfty), "blocks": int(row.blocks),
            "pa_total": int(row.pa), "pa_pg": round(float(row.pa / row.g), 1),
        })
    if t in proj:
        p["proj"] = proj[t]
        p["proj_src"] = "dst-model"
        p["opp"] = ctx[t]["opp"]
        p["home"] = ctx[t]["home"]
        p["dst_ctx"] = ctx[t]
        hits += 1

json.dump(players, open(f"{OUT}/players.json", "w"),
          separators=(",", ":"), allow_nan=False)

meta = json.load(open(f"{OUT}/meta.json"))
meta["dst"] = {
    "scoring": "1 sack, 2 INT, 2 fumble rec, 6 TD, 2 safety, 2 block, PA tiers",
    "pa_tiers": [[lo, hi, pts] for lo, hi, pts in PA_TIERS],
    "projection": "opponent implied total from the betting line, plus shrunk "
                  "team sack and takeaway rates",
    "league_rates": {"sacks_per_game": round(float(lg_sack), 2),
                     "takeaways_per_game": round(float(lg_ta), 2)},
    "through_week": COMPLETED,
}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)

print(f"D/ST built for {hits} teams, through week {COMPLETED}, "
      f"projecting week {UPCOMING}")
print(f"league averages: {lg_sack:.2f} sacks, {lg_ta:.2f} takeaways per game\n")
rank = sorted([p for p in players if p["pos"] == "DST" and p.get("proj")],
              key=lambda x: -x["proj"])
print(f"{'D/ST':10} {'proj':>6} {'opp':>5} {'implied':>8} {'ppg':>6} {'PA/g':>6}  season")
for p in rank[:10]:
    c = p["dst_ctx"]
    print(f"{p['name']:10} {p['proj']:6.1f} {('@' if not c['home'] else 'vs')+c['opp']:>5} "
          f"{c['opp_implied']:8.1f} {p.get('ppg', 0):6.1f} {p.get('pa_pg', 0):6.1f}  "
          f"{p.get('sacks',0):.0f} sk, {p.get('ints',0)} int, {p.get('def_tds',0)} td")
print("\nworst matchups:")
for p in rank[-4:]:
    c = p["dst_ctx"]
    print(f"{p['name']:10} {p['proj']:6.1f} {('@' if not c['home'] else 'vs')+c['opp']:>5} "
          f"{c['opp_implied']:8.1f}")
