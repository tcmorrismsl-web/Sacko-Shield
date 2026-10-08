#!/usr/bin/env python3
"""This week's head-to-head, and when every game actually kicks off.

The live tab needs three things the app doesn't otherwise have: who Tyler is
playing, which starters each side is fielding this week (a roster's `starters`
list can differ week to week), and enough schedule detail to tell a game that
hasn't started from one in progress from one that's over.

Kickoff times in games.csv are US Eastern; they're converted to UTC here so the
page can compare them to the viewer's clock wherever they are.
"""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd

D = "/home/claude/data"
OUT = "/home/claude/app/data"
WEEK = 3
EASTERN_OFFSET = -4          # EDT, in effect through the September slate
GAME_MINUTES = 190           # a regulation NFL game, wall clock, generously

TEAM_FIX = {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV",
            "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
fix = lambda t: TEAM_FIX.get(str(t).strip().upper(), str(t).strip().upper())

# roster_id|matchup_id|points|starters   — read from the Sleeper matchups endpoint
RAW = """1|3|0.0|12508,12507,13287,9754,11630,8180,10859,8228,11583,12533
2|5|0.0|12522,9509,9226,9488,11625,10229,4217,11584,5892,5849
3|4|0.0|12545,9221,13286,9756,11635,8137,10236,10222,11632,6904
4|1|0.0|421,8150,12529,6801,2216,7525,8130,4199,8146,4046
5|2|0.0|11560,8138,4866,7571,9486,9500,8131,7021,11586,4881
6|4|0.0|6797,12527,7543,7526,8121,11631,9484,7002,7553,7523
7|2|0.0|9228,4034,6790,7564,6786,11646,2505,4037,11834,3163
8|3|0.0|4984,8151,3198,8144,2133,5927,8110,12490,7594,11563
9|5|0.0|8183,9224,8155,6794,12519,8167,5012,12512,8148,4892
10|1|0.0|6770,6813,7588,7547,12526,9487,1466,12481,12514,3294"""

# -------------------------------------------------------------- kickoff times
g = pd.read_csv(f"{D}/games.csv", low_memory=False)
g26 = g[(g.season == 2026)].copy()
for c in ("home_team", "away_team"):
    g26[c] = g26[c].map(fix)

kick = {}
for _, r in g26.iterrows():
    if pd.isna(r.gameday) or pd.isna(r.gametime):
        continue
    hh, mm = str(r.gametime).split(":")[:2]
    naive = datetime.strptime(f"{r.gameday} {hh}:{mm}", "%Y-%m-%d %H:%M")
    utc = (naive - timedelta(hours=EASTERN_OFFSET)).replace(tzinfo=timezone.utc)
    entry = {"kick": utc.isoformat().replace("+00:00", "Z"),
             "end": (utc + timedelta(minutes=GAME_MINUTES))
                    .isoformat().replace("+00:00", "Z"),
             "final": bool(pd.notna(r.home_score))}
    kick.setdefault(str(int(r.week)), {})[r.home_team] = dict(entry, opp=r.away_team, home=True)
    kick[str(int(r.week))][r.away_team] = dict(entry, opp=r.home_team, home=False)

sched = json.load(open(f"{OUT}/schedule.json"))
sched["kickoffs"] = kick
json.dump(sched, open(f"{OUT}/schedule.json", "w"),
          separators=(",", ":"), allow_nan=False)

# ------------------------------------------------------------------ matchups
pairs, by_roster = {}, {}
for line in RAW.strip().splitlines():
    rid, mid, pts, starters = line.split("|")
    by_roster[rid] = {"matchup_id": mid, "points": float(pts),
                      "starters": [s for s in starters.split(",") if s]}
    pairs.setdefault(mid, []).append(rid)

leagues = json.load(open(f"{OUT}/leagues.json"))
for lg in leagues:
    if lg["source"] != "sleeper":
        continue
    lg["matchups"] = {str(WEEK): {
        "pairs": [{"matchup_id": mid, "rosters": rs} for mid, rs in sorted(pairs.items())],
        "by_roster": by_roster,
    }}
json.dump(leagues, open(f"{OUT}/leagues.json", "w"),
          separators=(",", ":"), allow_nan=False)

# --------------------------------------------------------------------- report
players = {p["id"]: p for p in json.load(open(f"{OUT}/players.json"))}
lg = next(l for l in leagues if l["source"] == "sleeper")
names = {r["id"]: r["name"] for r in lg["rosters"]}
mine = lg["my_team"]
my_mid = by_roster[mine]["matchup_id"]
opp = [r for r in pairs[my_mid] if r != mine][0]

print(f"week {WEEK} kickoffs stored for {len(kick.get(str(WEEK), {}))} teams")
print(f"\nmatchups:")
for mid, rs in sorted(pairs.items(), key=lambda x: int(x[0])):
    mark = "  <<< you" if mine in rs else ""
    print(f"  {names[rs[0]]:26} vs {names[rs[1]]:26}{mark}")
print(f"\nYour Week {WEEK} opponent: {names[opp]}")
for side, rid in (("you", mine), ("them", opp)):
    st = by_roster[rid]["starters"]
    print(f"\n  {side} — {names[rid]}")
    for s in st:
        p = players.get(s)
        print(f"    {p['pos']:4} {p['name']:24} {p['team']:4} "
              f"{'vs ' + (p.get('opp') or '—')}" if p else f"    ?? {s}")
