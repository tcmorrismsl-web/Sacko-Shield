#!/usr/bin/env python3
"""Points over expected.

nflverse doesn't publish ff_opportunity for 2026, so expected fantasy points
are modelled here from opportunity: how many carries, targets and pass
attempts a player got, priced at his own position's league-average value per
opportunity. POE is what he actually scored minus that.

It answers "is this production real, or is he running hot?" — which is the
question that matters on a waiver wire. A receiver with heavy targets and
negative POE is a buy; one with few targets and a big POE is a sell.

Expected receptions are stored alongside, so the app can restate POE under
half-PPR or standard scoring instead of assuming PPR.
"""
import json
import pandas as pd
import numpy as np

D = "/home/claude/data"
OUT = "/home/claude/app/data"

st = pd.read_csv(f"{D}/stats_week.csv", low_memory=False)
st = st[st.position.isin(["QB", "RB", "WR", "TE"])].copy()

num = ["carries", "rushing_yards", "rushing_tds", "targets", "receptions",
       "receiving_yards", "receiving_tds", "attempts", "passing_yards",
       "passing_tds", "passing_interceptions", "fantasy_points_ppr"]
for c in num:
    st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0)

# ---- league-average value of one opportunity, by position ------------------
# A position with almost none of some opportunity type (tight end carries, say)
# produces a wild rate off two goal-line gadget plays, so anything under this
# many opportunities falls back to the all-position rate.
MIN_OPPS = 150

def pool_rate(frame, kind):
    car, tgt, att = frame.carries.sum(), frame.targets.sum(), frame.attempts.sum()
    if kind == "per_carry":
        pts = 0.1 * frame.rushing_yards.sum() + 6 * frame.rushing_tds.sum()
        return pts / car if car else 0.0
    if kind == "per_target":
        pts = (0.1 * frame.receiving_yards.sum() + 6 * frame.receiving_tds.sum()
               + 1.0 * frame.receptions.sum())
        return pts / tgt if tgt else 0.0
    pts = (0.04 * frame.passing_yards.sum() + 4 * frame.passing_tds.sum()
           - 2 * frame.passing_interceptions.sum())
    return pts / att if att else 0.0

FALLBACK = {k: pool_rate(st, k) for k in ("per_carry", "per_target", "per_attempt")}

rates = {}
for pos, g in st.groupby("position"):
    car, tgt, att = g.carries.sum(), g.targets.sum(), g.attempts.sum()
    rush_pts = 0.1 * g.rushing_yards.sum() + 6 * g.rushing_tds.sum()
    rec_pts = (0.1 * g.receiving_yards.sum() + 6 * g.receiving_tds.sum()
               + 1.0 * g.receptions.sum())          # PPR
    pass_pts = (0.04 * g.passing_yards.sum() + 4 * g.passing_tds.sum()
                - 2 * g.passing_interceptions.sum())
    rates[pos] = {
        "per_carry": (rush_pts / car) if car >= MIN_OPPS else FALLBACK["per_carry"],
        "per_target": (rec_pts / tgt) if tgt >= MIN_OPPS else FALLBACK["per_target"],
        "per_attempt": (pass_pts / att) if att >= MIN_OPPS else FALLBACK["per_attempt"],
        "catch_rate": (g.receptions.sum() / tgt) if tgt >= MIN_OPPS else 0.65,
    }

print("value of one opportunity, PPR:")
for pos in ["QB", "RB", "WR", "TE"]:
    r = rates[pos]
    print(f"  {pos}: carry {r['per_carry']:.2f}  target {r['per_target']:.2f}  "
          f"attempt {r['per_attempt']:.2f}  catch rate {r['catch_rate']:.0%}")

# ---- per-player expectation ------------------------------------------------
import re, unicodedata

def norm_name(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

st["key"] = st.player_display_name.map(norm_name)
agg = st.groupby(["key", "position"]).agg(
    g=("week", "nunique"), carries=("carries", "sum"), targets=("targets", "sum"),
    attempts=("attempts", "sum"), receptions=("receptions", "sum"),
    actual=("fantasy_points_ppr", "sum")).reset_index()

poe = {}
for _, r in agg.iterrows():
    rt = rates.get(r.position)
    if not rt or r.g == 0:
        continue
    xfp = (r.carries * rt["per_carry"] + r.targets * rt["per_target"]
           + r.attempts * rt["per_attempt"])
    poe[r.key] = {
        "xfp": round(float(xfp), 2),
        "poe": round(float(r.actual - xfp), 2),
        "poe_g": round(float((r.actual - xfp) / r.g), 2),
        "x_rec": round(float(r.targets * rt["catch_rate"]), 2),
        "opps": int(r.carries + r.targets + r.attempts),
    }

players = json.load(open(f"{OUT}/players.json"))
hit = 0
for p in players:
    d = poe.get(p["key"])
    if d and p["pos"] in ("QB", "RB", "WR", "TE"):
        p.update(d); hit += 1
    else:
        p["xfp"] = p["poe"] = p["poe_g"] = p["x_rec"] = None
        p["opps"] = 0

json.dump(players, open(f"{OUT}/players.json", "w"),
          separators=(",", ":"), allow_nan=False)

meta = json.load(open(f"{OUT}/meta.json"))
meta["poe"] = {"method": "opportunity-priced expected points, PPR",
               "rates": {k: {kk: round(vv, 4) for kk, vv in v.items()}
                         for k, v in rates.items()},
               "through_week": int(st.week.max())}
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)

print(f"\nPOE attached to {hit} players")
ranked = sorted([p for p in players if p.get("poe_g") is not None and p["opps"] >= 12],
                key=lambda x: -x["poe_g"])
print("\nrunning hottest (per game):")
for p in ranked[:6]:
    print(f"  {p['name']:24} {p['pos']:3} {p['poe_g']:+6.1f}  "
          f"actual {p['ppg']:.1f}/g vs expected {p['xfp']/p['g']:.1f}/g")
print("\nmost due for positive regression:")
for p in ranked[-6:]:
    print(f"  {p['name']:24} {p['pos']:3} {p['poe_g']:+6.1f}  "
          f"actual {p['ppg']:.1f}/g vs expected {p['xfp']/p['g']:.1f}/g")
