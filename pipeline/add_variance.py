#!/usr/bin/env python3
"""How much a weekly fantasy score actually varies.

A win probability is only as good as its variance. Rather than assume a
coefficient of variation per position, this measures one: for every player with
at least two games, take the spread of his own weekly scores, and pool those
within-player deviations by position.

Two games per player is a thin sample individually, but pooled across hundreds
of players it gives a usable estimate — each player contributes his own
deviation, and the pooled standard deviation is what the simulation needs.

The output is a linear fit of sigma against a player's mean, because a 20-point
player swings more in absolute terms than a 5-point one, and a floor so nobody
is modelled as certain.
"""
import json, re, unicodedata
import numpy as np
import pandas as pd

D = "/home/claude/data"
OUT = "/home/claude/app/data"

def norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

st = pd.read_csv(f"{D}/stats_week.csv", low_memory=False)
st = st[st.position.isin(["QB", "RB", "WR", "TE"])].copy()
st["fp"] = pd.to_numeric(st.fantasy_points_ppr, errors="coerce").fillna(0)
st["key"] = st.player_display_name.map(norm)

rows = []
for (key, pos), g in st.groupby(["key", "position"]):
    if len(g) < 2:
        continue
    vals = g.fp.to_numpy()
    rows.append({"pos": pos, "mean": vals.mean(),
                 "sd": vals.std(ddof=1)})
df = pd.DataFrame(rows)

# Defenses carry weekly points from the D/ST build. Kickers carry per-week stat
# lines instead, because their points depend on the league — so score those
# against one reference table purely to measure how much they move.
REF_K = {"fgm": 0, "fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3,
         "fgm_40_49": 4, "fgm_50p": 5, "fgmiss": -1, "xpm": 1, "xpmiss": -1}

extra = []
for p in json.load(open(f"{OUT}/players.json")):
    if p["pos"] == "DST" and p.get("logs") and len(p["logs"]) >= 2:
        v = np.array(p["logs"], dtype=float)
    elif p["pos"] == "K" and p.get("wstats") and len(p["wstats"]) >= 2:
        v = np.array([sum(val * REF_K.get(k, 0) for k, val in w.items())
                      for w in p["wstats"]], dtype=float)
    else:
        continue
    extra.append({"pos": p["pos"], "mean": v.mean(), "sd": v.std(ddof=1)})
if extra:
    df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)

model = {}
print(f"{'pos':5} {'players':>8} {'mean sd':>8} {'slope':>7} {'intercept':>10} {'CV':>6}")
for pos, g in df.groupby("pos"):
    g = g[g["mean"] > 0.5]
    if len(g) < 12:
        continue
    # sigma ≈ a + b·mean, fit by least squares, clipped to stay sane
    b, a = np.polyfit(g["mean"], g["sd"], 1)
    b = float(np.clip(b, 0.10, 1.10))
    a = float(np.clip(a, 0.5, 9.0))
    model[pos] = {"intercept": round(a, 3), "slope": round(b, 4),
                  "floor": round(max(1.5, a * 0.6), 2),
                  "n": int(len(g))}
    cv = (g["sd"] / g["mean"]).replace([np.inf, -np.inf], np.nan).dropna().median()
    print(f"{pos:5} {len(g):8} {g['sd'].mean():8.2f} {b:7.3f} {a:10.2f} {cv:6.2f}")

# positions with too few observations inherit the closest sensible neighbour
for pos, fallback in [("K", "TE"), ("DST", "TE")]:
    if pos not in model and fallback in model:
        model[pos] = dict(model[fallback], inherited_from=fallback)

meta = json.load(open(f"{OUT}/meta.json"))
meta["variance"] = {
    "method": "pooled within-player weekly standard deviation, 2026 to date",
    "form": "sigma = intercept + slope * projected points, floored",
    "by_pos": model,
    "through_week": int(st.week.max()),
}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)
print("\nstored:", json.dumps(model, indent=1))
