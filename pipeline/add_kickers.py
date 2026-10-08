#!/usr/bin/env python3
"""Kickers, scored the way leagues actually score them.

Kickers were the last position riding a generic positional curve. Almost every
league pays field goals by distance — Tyler's pays 3/3/3/4/6 and zero for the
flat "field goal made" key — so a single points number is meaningless for them.

Both the projection and the season are therefore stored as stat lines keyed by
Sleeper's own scoring names, exactly like the skill positions:

  fgm, fgm_0_19, fgm_20_29, fgm_30_39, fgm_40_49, fgm_50p, fgmiss, xpm, xpmiss

The flat `fgm` key is kept alongside the buckets on purpose. Sleeper treats
buckets as full replacements with `fgm` additive on top (Tyler's league sets
`fgm` to 0), while some leagues pay a flat `fgm` with no buckets at all, and
others pay flat plus a long-distance bonus. Storing both and letting the league
multiply handles all three without a special case.
"""
import json, re, unicodedata
import pandas as pd

D = "/home/claude/data"
FEEDS = "/home/claude/feeds"
OUT = "/home/claude/app/data"

def norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

# ---------------------------------------------------------- season stat lines
st = pd.read_csv(f"{D}/stats_week.csv", low_memory=False)
k = st[st.position == "K"].copy()
num = ["fg_made", "fg_att", "fg_missed", "fg_made_0_19", "fg_made_20_29",
       "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
       "pat_made", "pat_att", "pat_missed"]
for c in num:
    k[c] = pd.to_numeric(k[c], errors="coerce").fillna(0)
k["key"] = k.player_display_name.map(norm)
k["fgm_50p"] = k.fg_made_50_59 + k.fg_made_60_
k["xpmiss"] = (k.pat_att - k.pat_made).clip(lower=0)
k["fgmiss"] = (k.fg_att - k.fg_made).clip(lower=0)

SEASON_KEYS = {
    "fgm": "fg_made", "fgm_0_19": "fg_made_0_19", "fgm_20_29": "fg_made_20_29",
    "fgm_30_39": "fg_made_30_39", "fgm_40_49": "fg_made_40_49",
    "fgm_50p": "fgm_50p", "fgmiss": "fgmiss", "xpm": "pat_made",
    "xpmiss": "xpmiss",
}

season = k.groupby("key").agg(
    g=("week", "nunique"),
    **{out: (src, "sum") for out, src in SEASON_KEYS.items()}).reset_index()

weekly = {key: grp.sort_values("week") for key, grp in k.groupby("key")}

# ----------------------------------------------------- projected stat lines
# name|team|fgm|fgm_0_19|fgm_20_29|fgm_30_39|fgm_40_49|fgm_50p|fga|xpm|xpa
proj = {}
for line in open(f"{FEEDS}/k.txt"):
    line = line.strip()
    if not line or line.startswith(("KEYS", "COUNT")):
        continue
    f = line.split("|")
    if len(f) != 11:
        print("  skipped malformed line:", f[0])
        continue
    name, _team = f[0], f[1]
    fgm, b019, b2029, b3039, b4049, b50p, fga, xpm, xpa = map(float, f[2:])
    stats = {
        "fgm": fgm, "fgm_0_19": b019, "fgm_20_29": b2029, "fgm_30_39": b3039,
        "fgm_40_49": b4049, "fgm_50p": b50p,
        "fgmiss": max(0.0, fga - fgm), "xpm": xpm,
        "xpmiss": max(0.0, xpa - xpm),
    }
    proj[norm(name)] = {kk: round(vv, 3) for kk, vv in stats.items() if vv}

# --------------------------------------------------------------------- attach
players = json.load(open(f"{OUT}/players.json"))
sdict = {r.key: r for _, r in season.iterrows()}

hit_p, hit_s, missing = 0, 0, []
for p in players:
    if p["pos"] != "K":
        continue
    pr = proj.get(p["key"])
    if pr:
        p["pstats"] = pr
        hit_p += 1
    else:
        p["pstats"] = None
    s = sdict.get(p["key"])
    if s is not None:
        p["sstats"] = {kk: float(s[kk]) for kk in SEASON_KEYS if float(s[kk])}
        p["g"] = int(s.g)
        hit_s += 1
        w = weekly.get(p["key"])
        if w is not None:
            # a kicker's weekly log has to be scored by the league too, so the
            # per-week stat lines travel with him
            p["wstats"] = [
                {kk: float(row[src]) for kk, src in SEASON_KEYS.items()
                 if float(row[src])}
                for _, row in w.iterrows()]
            p["logw"] = [int(x) for x in w.week.tolist()]
            p["logs"] = None          # points are computed per league, not here
    else:
        p["sstats"] = None

# A starting kicker absent from the id sources is still a starting kicker —
# create the row rather than leaving a hole where a league has a K slot.
feed_teams = {}
for line in open(f"{FEEDS}/k.txt"):
    f = line.strip().split("|")
    if len(f) == 11:
        feed_teams[norm(f[0])] = (f[0], f[1])

for key in proj:
    if any(p["key"] == key and p["pos"] == "K" for p in players):
        continue
    disp, team = feed_teams.get(key, (key.title(), "FA"))
    s = sdict.get(key)
    row = {
        "id": "k_" + key.replace(" ", "_"), "key": key, "name": disp, "pos": "K",
        "team": team, "age": None, "exp": None, "draft_year": None,
        "espn": None, "sleeper": None, "status": "ACT",
        "v_sf": None, "v_1qb": None, "ecr_dyn_sf": None, "ecr_dyn_1qb": None,
        "ecr_rookie": None, "ecr_ros": None, "ecr_ros_overall": None,
        "own": None, "bye": None,
        "wk_ecr": None, "wk_pos_rank": None, "wk_proj": None, "wk_grade": None,
        "wk_opp": None, "wk_sd": None,
        "g": int(s.g) if s is not None else 0,
        "pts": None, "ppg": None, "logs": None, "logw": [],
        "tgt": None, "rec": None, "recyd": None, "rectd": None, "car": None,
        "ruyd": None, "rutd": None, "payd": None, "patd": None, "int": None,
        "tgt_share": None, "wopr": None, "snap": None, "snap_last": None,
        "inj": None, "inj_note": None, "inj_week": None,
        "proj": None, "proj_src": "model", "proj_parts": None, "par": None,
        "xfp": None, "poe": None, "poe_g": None, "x_rec": None, "opps": 0,
        "pstats": proj[key],
        "sstats": ({kk: float(s[kk]) for kk in SEASON_KEYS if float(s[kk])}
                   if s is not None else None),
        "created_from": "kicker feed",
    }
    if s is not None:
        w = weekly.get(key)
        if w is not None:
            row["wstats"] = [
                {kk: float(r[src]) for kk, src in SEASON_KEYS.items() if float(r[src])}
                for _, r in w.iterrows()]
            row["logw"] = [int(x) for x in w.week.tolist()]
    players.append(row)
    missing.append(f"{disp} ({team}) — added")

json.dump(players, open(f"{OUT}/players.json", "w"),
          separators=(",", ":"), allow_nan=False)

meta = json.load(open(f"{OUT}/meta.json"))
meta["kickers"] = {
    "projection": "Sleeper stat line by field-goal distance bucket",
    "season": "nflverse field-goal distance buckets and extra points",
    "note": "points are computed per league; nflverse does not score kickers",
}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)

print(f"kickers: {hit_p} with a projected stat line, {hit_s} with a season line")
if missing:
    print("kickers created from the feed:", missing)

HIS = {"fgm": 0.0, "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3,
       "fgm_40_49": 4, "fgm_50p": 6, "fgmiss": -1, "xpm": 1, "xpmiss": -1}
FLAT = {"fgm": 3, "fgmiss": -1, "xpm": 1, "xpmiss": -1}
score = lambda st, sc: sum(v * sc.get(kk, 0) for kk, v in (st or {}).items())

rows = [(p, score(p.get("pstats"), HIS), score(p.get("pstats"), FLAT))
        for p in players if p["pos"] == "K" and p.get("pstats")]
rows.sort(key=lambda r: -r[1])
print(f"\n{'kicker':22} {'his league':>11} {'flat 3/FG':>10}  season so far")
for p, h, fl in rows[:8]:
    s_his = score(p.get("sstats"), HIS)
    print(f"{p['name']:22} {h:11.2f} {fl:10.2f}  {s_his:.0f} pts in {p.get('g', 0)}")
