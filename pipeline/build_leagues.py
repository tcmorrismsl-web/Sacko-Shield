#!/usr/bin/env python3
"""Assemble every league Tyler plays in into one file.

Sleeper comes through complete and verified. ESPN's roster payloads truncate
in transit and the extraction cross-contaminated two different leagues, so
those leagues carry only what was verified — settings and standings — and are
marked as such rather than filled with plausible-looking guesses.
"""
import json

import os

OUT = "/home/claude/app/data"
# The Sleeper league is built by sleeper_league.py; once it has been folded into
# leagues.json, read it back from there so this stays re-runnable.
if os.path.exists(f"{OUT}/league.json"):
    sleeper = json.load(open(f"{OUT}/league.json"))
else:
    sleeper = next(l for l in json.load(open(f"{OUT}/leagues.json"))
                   if l["source"] == "sleeper")
sleeper["key"] = "sleeper-" + str(sleeper["league_id"])
sleeper["status"] = "full"
sleeper["platform"] = "Sleeper"
# read from the Sleeper API — the league pays 6 per passing TD and
# 0.05 per passing yard, not the 4 and 0.04 public projections assume
sleeper["scoring_settings"] = json.load(open("/home/claude/scoring_sleeper.json"))

ESPN_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K"] + ["BN"] * 7

def espn(key, league_id, name, teams, scoring, standings, my_team, note):
    return {
        "key": "espn-" + league_id, "sample": False, "source": "espn", "platform": "ESPN",
        "name": name, "league_id": league_id, "season": 2026, "type": "redraft",
        "teams": teams, "scoring": scoring, "roster_positions": ESPN_SLOTS,
        "my_team": my_team, "status": "standings_only", "note": note,
        "scoring_settings": ({"rec": 0.5} if scoring == "half"
                             else {"rec": 1.0} if scoring == "ppr" else None),
        "scoring_partial": True,
        "rosters": [{"id": str(t[0]), "name": t[1], "owner": t[4] if len(t) > 4 else "",
                     "players": [], "starters": [], "picks": [],
                     "wins": t[2].split("-")[0] and int(t[2].split("-")[0]),
                     "losses": int(t[2].split("-")[1]), "pf": t[3], "pa": 0.0}
                    for t in standings],
        "results": [],
    }

QUAD_NOTE = ("ESPN serves this league's name and standings but refuses the settings "
             "and roster views without your espn_s2 and SWID cookies, so scoring "
             "rules and rosters are unknown here. Standings below are verified.")

NOTE = ("ESPN returns this league's rosters in a payload that truncates before it "
        "reaches Claude — two separate pulls came back with the same players on "
        "teams in different leagues. Standings and settings below are verified; "
        "rosters are not loaded rather than guessed at.")

# League IDs, names, team names and managers live in a git-ignored file so the
# public repo never carries them. Each entry: league_id, name, teams, scoring,
# my_team, note ("default" or "quad"), standings [[id, team, "W-L", pf, owner]].
PRIVATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "espn", "leagues_private.json")
leagues = [sleeper] + [
    espn(None, str(c["league_id"]), c["name"], c["teams"], c["scoring"],
         [tuple(t) for t in c["standings"]], str(c["my_team"]),
         QUAD_NOTE if c.get("note") == "quad" else NOTE)
    for c in json.load(open(PRIVATE))
]

json.dump(leagues, open(f"{OUT}/leagues.json", "w"), separators=(",", ":"),
          allow_nan=False)

for lg in leagues:
    print(f"{lg['platform']:8} {lg['name'][:34]:36} {str(lg['teams']):>4} teams  "
          f"{lg['scoring']:5} {lg['status']}")
    if lg["status"] == "full":
        mine = next(r for r in lg["rosters"] if r["id"] == lg["my_team"])
        print(f"         → you: {mine['name']} ({mine['wins']}-{mine['losses']}, "
              f"{len(mine['players'])} players)")
    elif lg["my_team"]:
        mine = next(r for r in lg["rosters"] if r["id"] == lg["my_team"])
        print(f"         → you: {mine['name']} ({mine['wins']}-{mine['losses']}, "
              f"{mine['pf']} PF)")
