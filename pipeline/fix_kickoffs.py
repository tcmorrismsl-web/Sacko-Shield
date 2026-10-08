#!/usr/bin/env python3
"""Put kickoff times in UTC, which is what the app compares them against.

nflverse `games.csv` gives `gameday` and `gametime` as US Eastern wall-clock
time. The Oct 1 rebuild wrote them into `schedule.json` with a `Z` on the end
and no conversion, so every kickoff was 4 hours early: Thursday Night Football
at 8:15pm ET became 20:15 UTC, which is 4:15pm ET. The app uses these to decide
whether a game is upcoming, live or over, and how often to poll — so during
games it was calling contests final before they had started.

This converts with real time-zone rules rather than a fixed +4, because
daylight saving ends on Nov 1, 2026 and every game after that is +5. It also
cross-checks each stored wall-clock time against games.csv and refuses to run
if they disagree, so it cannot silently "fix" a time that was already right.
"""
import csv, json, pathlib, sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
GAME_MINUTES = 190
SCHED = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/home/claude/app/data/schedule.json")
GAMES = pathlib.Path("/home/claude/data/games.csv")

FIX = {"JAC": "JAX", "LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV",
       "WSH": "WAS", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
fix = lambda t: FIX.get(str(t).strip().upper(), str(t).strip().upper())

# games.csv: the source of truth for the Eastern wall clock
truth = {}
for r in csv.DictReader(open(GAMES)):
    if r["season"] != "2026" or not r["gameday"] or not r["gametime"]:
        continue
    hh, mm = r["gametime"].split(":")[:2]
    wall = f"{r['gameday']}T{int(hh):02d}:{int(mm):02d}"
    for t in (fix(r["home_team"]), fix(r["away_team"])):
        truth[(r["week"], t)] = wall

S = json.loads(SCHED.read_text())
K = S["kickoffs"]

already_utc, converted, mismatched, unknown = 0, 0, [], 0
for wk, teams in K.items():
    for team, g in teams.items():
        stored_wall = g["kick"][:16]                       # "YYYY-MM-DDTHH:MM"
        expect = truth.get((wk, team))
        if expect is None:
            unknown += 1
            continue
        # Already UTC?  Then stored != ET wall clock, and converting the ET wall
        # clock reproduces the stored value.
        utc_from_truth = (datetime.fromisoformat(expect).replace(tzinfo=ET)
                          .astimezone(timezone.utc))
        if g["kick"] == utc_from_truth.strftime("%Y-%m-%dT%H:%M:%SZ"):
            already_utc += 1
            continue
        if stored_wall != expect:
            mismatched.append((wk, team, g["kick"], expect))
            continue
        g["kick"] = utc_from_truth.strftime("%Y-%m-%dT%H:%M:%SZ")
        g["end"] = (utc_from_truth + timedelta(minutes=GAME_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
        converted += 1

if mismatched:
    print("REFUSING: stored kickoff disagrees with games.csv for", len(mismatched), "entries:")
    for m in mismatched[:10]:
        print("  week", m[0], m[1], "stored", m[2], "games.csv ET", m[3])
    sys.exit(1)

SCHED.write_text(json.dumps(S, separators=(",", ":"), allow_nan=False))
print(f"converted {converted} kickoffs ET->UTC, {already_utc} were already UTC, "
      f"{unknown} had no games.csv row")

# ---- independent checks on the result, not on the code that produced it
def kick(wk, team): return K[str(wk)][team]["kick"]
checks = []
# Thursday Night Football, week 4: PIT at CLE, 8:15pm EDT
checks.append(("TNF wk4 PIT kicks 00:15Z Friday", kick(4, "PIT") == "2026-10-02T00:15:00Z", kick(4, "PIT")))
# every Thursday game, through the whole season, lands on Friday 00:xx or 01:xx UTC
thu = []
for wk, teams in K.items():
    for team, g in teams.items():
        dt = datetime.fromisoformat(g["kick"].replace("Z", "+00:00"))
        et = dt.astimezone(ET)
        if et.weekday() == 3:                               # Thursday, Eastern
            thu.append((wk, team, g["kick"], et.strftime("%a %H:%M %Z")))
# Thanksgiving (4th Thursday of November) has the traditional afternoon games —
# Detroit at 12:30/1pm and Dallas at 4:30pm Eastern — so it is the one Thursday
# where a daytime kickoff is correct rather than a missed conversion.
def thanksgiving(et):
    return et.month == 11 and et.weekday() == 3 and 22 <= et.day <= 28
bad_thu = []
for wk, teams in K.items():
    for team, g in teams.items():
        et = datetime.fromisoformat(g["kick"].replace("Z", "+00:00")).astimezone(ET)
        if et.weekday() == 3 and not thanksgiving(et) and not (19 <= et.hour <= 21):
            bad_thu.append((wk, team, g["kick"]))
checks.append(("every non-Thanksgiving Thursday game is an evening game in Eastern time",
               not bad_thu, f"{len(thu)} Thursday entries, {len(bad_thu)} odd"))
# a Sunday 1pm ET game before and after the Nov 1 DST change
pre = [(w, t) for (w, t), v in truth.items() if v.endswith("T13:00") and v < "2026-11-01"]
post = [(w, t) for (w, t), v in truth.items() if v.endswith("T13:00") and v > "2026-11-02"]
if pre:
    w, t = pre[0]; checks.append(("1pm ET in October = 17:00Z", kick(w, t).endswith("T17:00:00Z"), f"wk{w} {t} {kick(w, t)}"))
if post:
    w, t = post[0]; checks.append(("1pm ET after DST ends = 18:00Z", kick(w, t).endswith("T18:00:00Z"), f"wk{w} {t} {kick(w, t)}"))
print()
ok = True
for name, passed, detail in checks:
    ok &= passed
    print(("  ok  " if passed else "  FAIL"), name, "—", detail)
sys.exit(0 if ok else 1)
