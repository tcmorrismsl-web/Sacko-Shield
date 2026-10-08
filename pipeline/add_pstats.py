#!/usr/bin/env python3
"""Store projected STAT LINES, not projected points.

A projection expressed as "21.9 points" is only true under the scoring that
produced it. Tyler's dynasty league pays 6 per passing touchdown and 0.05 per
passing yard, not the 4 and 0.04 baked into every public projection — Lamar
Jackson is 24.5 points under the default and 29.9 under his league.

So the projection stored here is the stat line Sleeper expects, and the app
multiplies it by whatever the league actually pays. Same for season production,
which is restated from its own component totals.

Keys use Sleeper's own scoring_settings names, so a league's settings object
multiplies against them directly with no translation table.
"""
import json, re, unicodedata

FEEDS = "/home/claude/feeds"
OUT = "/home/claude/app/data"

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

# file -> (position, column names after name and team)
LAYOUT = {
    "qb.txt": ("QB", ["pass_yd", "pass_td", "pass_int", "rush_yd", "rush_td",
                      "rec", "rec_yd", "rec_td", "fum_lost"]),
    "rb.txt": ("RB", ["rush_yd", "rush_td", "rec", "rec_yd", "rec_td", "fum_lost"]),
    "wr.txt": ("WR", ["rush_yd", "rush_td", "rec", "rec_yd", "rec_td", "fum_lost"]),
    "te.txt": ("TE", ["rush_yd", "rush_td", "rec", "rec_yd", "rec_td", "fum_lost"]),
}

feed = {}
for fname, (pos, cols) in LAYOUT.items():
    for line in open(f"{FEEDS}/{fname}"):
        line = line.strip()
        if not line or line.startswith("COUNT"):
            continue
        parts = line.split("|")
        name, team, vals = parts[0], parts[1], parts[2:]
        if len(vals) != len(cols):
            print(f"  skipped malformed line: {name}")
            continue
        stats = {c: float(v) for c, v in zip(cols, vals) if float(v) != 0}
        feed[(norm(name), pos)] = {"team": team, "stats": stats}

players = json.load(open(f"{OUT}/players.json"))
hit, miss = 0, []
for p in players:
    d = feed.get((p["key"], p["pos"]))
    if d:
        p["pstats"] = d["stats"]
        hit += 1
    elif p["pos"] in ("QB", "RB", "WR", "TE"):
        p["pstats"] = None

for k in feed:
    if not any(p["key"] == k[0] and p["pos"] == k[1] for p in players):
        miss.append(k)

# season production, as component totals under the same key names, so a league's
# scoring can restate the season the same way it restates the projection
for p in players:
    if p["pos"] in ("QB", "RB", "WR", "TE"):
        p["sstats"] = {k: v for k, v in {
            "pass_yd": p.get("payd"), "pass_td": p.get("patd"),
            "pass_int": p.get("int"), "rush_yd": p.get("ruyd"),
            "rush_td": p.get("rutd"), "rec": p.get("rec"),
            "rec_yd": p.get("recyd"), "rec_td": p.get("rectd"),
        }.items() if v}
    elif p["pos"] == "DST":
        p["sstats"] = {k: v for k, v in {
            "sack": p.get("sacks"), "int": p.get("ints"),
            "fum_rec": p.get("fumbles_rec"), "def_td": p.get("def_tds"),
            "safe": p.get("safeties"), "blk_kick": p.get("blocks"),
        }.items() if v}

json.dump(players, open(f"{OUT}/players.json", "w"),
          separators=(",", ":"), allow_nan=False)

print(f"stat lines attached to {hit} players")
if miss:
    print(f"feed names that matched nothing ({len(miss)}):",
          [f"{n} ({pos})" for n, pos in miss][:10])

# --- show the damage the old assumption was doing --------------------------
HIS = {"pass_yd": 0.05, "pass_td": 6.0, "pass_int": -2.0, "rush_yd": 0.1,
       "rush_td": 6.0, "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "fum_lost": -2.0}
STD = {"pass_yd": 0.04, "pass_td": 4.0, "pass_int": -1.0, "rush_yd": 0.1,
       "rush_td": 6.0, "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "fum_lost": -2.0}
score = lambda st, sc: sum(v * sc.get(k, 0) for k, v in (st or {}).items())

rows = [(p, score(p.get("pstats"), HIS), score(p.get("pstats"), STD))
        for p in players if p.get("pstats")]
rows.sort(key=lambda r: -(r[1] - r[2]))
print("\nbiggest swing between the default scoring and his league:")
print(f"  {'player':22} {'pos':4} {'default':>8} {'his league':>11} {'diff':>7}")
for p, h, s in rows[:8]:
    print(f"  {p['name']:22} {p['pos']:4} {s:8.1f} {h:11.1f} {h - s:+7.1f}")
print("  ...")
for p, h, s in rows[-3:]:
    print(f"  {p['name']:22} {p['pos']:4} {s:8.1f} {h:11.1f} {h - s:+7.1f}")
