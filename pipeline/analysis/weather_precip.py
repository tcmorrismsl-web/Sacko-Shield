"""Measure what rain and snow do to NFL team output, 2016-2025.

nflverse games.csv has kickoff temp and wind but no precipitation, so the
precipitation label comes from the play-by-play `weather` text recorded for
each game ("Rain Temp: 45° F, ..."). Forecast-style wording ("chance of rain",
"rain possible", "expected") is not counted as precipitation.

Method matches docs/weather.md: each team-game's stat is compared with the
same team's season average with that game left out, so team quality drops out.
Ratios are sum(actual) / sum(expected) over the group. Standard errors come
from a bootstrap over games. Outdoor regular-season games only.

Usage: python3 weather_precip.py DATA_DIR   (games.csv, stats_team_week_YYYY.csv,
game_weather.json — {game_id: weather text} pulled from play_by_play_YYYY.csv.gz)
"""
import csv, json, re, sys, random, collections

D = sys.argv[1]
wx = json.load(open(f"{D}/game_weather.json"))
FORECAST = re.compile(r"chance|possible|threat|likely|forecast|expected|\d+ ?%")
SNOW = re.compile(r"snow|flurr|blizzard|sleet|flakes")
RAIN = re.compile(r"rain|shower|drizzl|storm|thunder|misty")

LIGHT = {g: bool(re.search(r"light|drizzl|misty|scattered|few", t.split("Temp:")[0].lower())) for g, t in wx.items()}

def precip(text):
    d = text.split("Temp:")[0].lower()
    if FORECAST.search(d):
        return "dry"
    if SNOW.search(d):
        return "snow"
    if RAIN.search(d):
        return "rain"
    return "dry"

games = {}
for r in csv.DictReader(open(f"{D}/games.csv")):
    if r["game_type"] != "REG" or not (2016 <= int(r["season"]) <= 2025):
        continue
    if r["roof"] not in ("outdoors", "open"):
        continue
    try:
        t, w = float(r["temp"]), float(r["wind"])
    except ValueError:
        continue
    games[r["game_id"]] = {"temp": t, "wind": w, "p": precip(wx.get(r["game_id"], "")),
                           "pts": {r["home_team"]: float(r["home_score"] or 0),
                                   r["away_team"]: float(r["away_score"] or 0)}}

STATS = {
    "pass_yds": lambda r: f(r, "passing_yards"),
    "pass_td": lambda r: f(r, "passing_tds"),
    "completions": lambda r: f(r, "completions"),
    "pass_att": lambda r: f(r, "attempts"),
    "rush_att": lambda r: f(r, "carries"),
    "rush_yds": lambda r: f(r, "rushing_yards"),
    "rush_td": lambda r: f(r, "rushing_tds"),
    "fumbles_lost": lambda r: f(r, "sack_fumbles_lost") + f(r, "rushing_fumbles_lost") + f(r, "receiving_fumbles_lost"),
    "ints_thrown": lambda r: f(r, "passing_interceptions"),
    "sacks_taken": lambda r: f(r, "sacks_suffered"),
}
def f(r, k):
    try: return float(r[k] or 0)
    except (KeyError, ValueError): return 0.0

rows = []  # (season, team, game_id, {stat: value}) for ALL reg games (indoor too, for team averages)
for y in range(2016, 2026):
    for r in csv.DictReader(open(f"{D}/stats_team_week_{y}.csv")):
        if r["season_type"] != "REG":
            continue
        v = {k: fn(r) for k, fn in STATS.items()}
        g = games.get(r["game_id"])
        v["points"] = g["pts"].get(r["team"], 0.0) if g else None
        rows.append((y, r["team"], r["game_id"], v))

by_team = collections.defaultdict(list)
for row in rows:
    by_team[(row[0], row[1])].append(row)

obs = []  # (game_id, precip, temp, wind, actual{}, expected{})
for key, lst in by_team.items():
    n = len(lst)
    if n < 6:
        continue
    tot = collections.Counter()
    cnt = collections.Counter()
    for _, _, _, v in lst:
        for k, x in v.items():
            if x is not None:
                tot[k] += x; cnt[k] += 1
    for _, _, gid, v in lst:
        g = games.get(gid)
        if not g:
            continue
        exp = {}
        for k, x in v.items():
            if x is None or cnt[k] < 2:
                continue
            exp[k] = (tot[k] - x) / (cnt[k] - 1)
        obs.append((gid, g["p"], g["temp"], g["wind"], v, exp))

def ratio(sel, stat):
    a = sum(o[4][stat] for o in sel if stat in o[5] and o[4][stat] is not None)
    e = sum(o[5][stat] for o in sel if stat in o[5])
    return a / e if e else None

def boot(sel, stat, B=400):
    by_g = collections.defaultdict(list)
    for o in sel: by_g[o[0]].append(o)
    keys = list(by_g)
    rnd = random.Random(7); vals = []
    for _ in range(B):
        s = [o for k in (rnd.choice(keys) for _ in keys) for o in by_g[k]]
        r = ratio(s, stat)
        if r: vals.append(r)
    m = sum(vals) / len(vals)
    return (sum((x - m) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5

out = {}
groups = {
    # precipitation, any temperature/wind — the raw effect
    "dry_all": lambda o: o[1] == "dry",
    "rain_all": lambda o: o[1] == "rain",
    "snow_all": lambda o: o[1] == "snow",
    # precipitation in calm, mild games, so wind and cold aren't counted again
    "dry_calm_mild": lambda o: o[1] == "dry" and o[3] < 10 and o[2] > 40,
    "rain_calm_mild": lambda o: o[1] == "rain" and o[3] < 10 and o[2] > 40,
    # rain on top of wind 10+ (the stacking question)
    "dry_windy": lambda o: o[1] == "dry" and o[3] >= 10,
    "rain_windy": lambda o: o[1] == "rain" and o[3] >= 10,
    # snow against dry games just as cold, so the cold effect isn't counted twice
    "dry_cold": lambda o: o[1] == "dry" and o[2] <= 40,
    "snow_cold": lambda o: o[1] == "snow" and o[2] <= 40,
    "rain_cold": lambda o: o[1] == "rain" and o[2] <= 40,
    # light rain vs heavier rain
    "rain_light": lambda o: o[1] == "rain" and LIGHT.get(o[0], False),
    "rain_steady": lambda o: o[1] == "rain" and not LIGHT.get(o[0], False),
}
for name, fn in groups.items():
    sel = [o for o in obs if fn(o)]
    g = len({o[0] for o in sel})
    out[name] = {"games": g, "team_games": len(sel)}
    for stat in list(STATS) + ["points"]:
        r = ratio(sel, stat)
        out[name][stat] = {"ratio": round(r, 3), "se": round(boot(sel, stat), 3)} if r else None
print(json.dumps(out, indent=1))
