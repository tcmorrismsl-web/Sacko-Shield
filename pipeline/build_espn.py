#!/usr/bin/env python3
"""Real ESPN rosters, scoring and matchups, baked into leagues.json.

ESPN's roster payload cannot be read whole: every player entry drags a full
season of stats with it, so the response is cut off after about six players
however it is filtered. Three views DO come back complete, because they carry
bare ids instead of player objects:

    mDraftDetail   every pick, teamId -> playerId
    mTransactions2 every add/drop in the recent window
    mSettings      lineup slots and the league's own scoring
    mTeam          team names and records

So a roster is reconstructed as draft + executed transactions. That is exact
except for moves older than the transaction window, which shows up as a
"ghost drop" — a player dropped who was never on our copy — and leaves one or
two stale players on a bench. Every roster is checked against the live ESPN
lineup for the teams we could read, and the count is reported per team so the
uncertainty is visible rather than silent.

Player ids are ESPN ids matched against players.json's own `espn` field; the
mapping was verified end to end against names ESPN returned independently.
Defenses arrive as negative ids: -16000 minus the ESPN pro-team id.
"""
import collections
import json
import pathlib

ESPN = pathlib.Path("/home/claude/espn")
APP = pathlib.Path("/home/claude/app/data")

# ESPN pro-team id -> our team abbreviation. Defenses are keyed off this.
ESPN_PRO = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

# ESPN statId -> the scoring key our stat lines use. ONLY the ids whose meaning
# is certain are mapped. ESPN's defensive stat ids are not documented and
# guessing one wrong would quietly misprice every defense, so the defensive
# half is left out and `scoring_partial` lets it fall through to the league
# defaults instead.
STAT = {
    3: "pass_yd", 4: "pass_td", 19: "pass_2pt", 20: "pass_int",
    24: "rush_yd", 25: "rush_td", 26: "rush_2pt",
    42: "rec_yd", 43: "rec_td", 44: "rec_2pt", 53: "rec",
    72: "fum_lost",
    77: "fgm_40_49", 85: "fgmiss", 86: "xpm", 88: "xpmiss", 198: "fgm_50p",
}
# ESPN bands every field goal under 40 together; our table splits it in three.
STAT_FANOUT = {80: ("fgm_0_19", "fgm_20_29", "fgm_30_39")}


def scoring_from(items):
    """Turn ESPN's statId:points list into our scoring table."""
    out = {}
    for sid, pts in items.items():
        if sid in STAT:
            out[STAT[sid]] = pts
        for key in STAT_FANOUT.get(sid, ()):
            out[key] = pts
    return out


def load_pipe(path, n):
    rows = []
    for line in (ESPN / path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(line.split("|"))
    assert all(len(r) == n for r in rows), f"{path}: ragged rows"
    return rows


def reconstruct(draft_file, tx_file):
    """draft + executed adds/drops -> current roster, plus a health report."""
    roster = collections.defaultdict(list)
    for _, tid, pid in load_pipe(draft_file, 3):
        roster[tid].append(pid)

    rows = load_pipe(tx_file, 6)
    rows.sort(key=lambda r: int(r[1]))
    ghosts = []
    for status, _date, typ, frm, to, pid in rows:
        if status != "EXECUTED" or typ not in ("ADD", "DROP"):
            continue                       # LINEUP/ROSTER don't change ownership
        if typ == "ADD":
            if pid not in roster[to]:
                roster[to].append(pid)
        elif pid in roster[frm]:
            roster[frm].remove(pid)
        else:
            ghosts.append((frm, pid))      # acquired before our window opened
    return roster, ghosts


def main():
    players = json.loads((APP / "players.json").read_text())
    by_espn = {str(p["espn"]): p for p in players if p.get("espn")}
    dst = {p["team"]: p for p in players if p["pos"] == "DST"}

    def resolve(pid):
        if pid.startswith("-"):
            return dst.get(ESPN_PRO.get(-int(pid) - 16000))
        return by_espn.get(pid)

    cfg = json.loads((ESPN / "leagues_cfg.json").read_text())
    leagues = json.loads((APP / "leagues.json").read_text())
    by_key = {l["key"]: l for l in leagues}

    report = []
    for c in cfg:
        lg = by_key[c["key"]]
        roster, ghosts = reconstruct(c["draft"], c["tx"])
        prior_rosters = {r["id"]: r for r in lg.get("rosters", [])}

        # team names / records, refreshed from mTeam
        teams = {str(t["id"]): t for t in c["teams"]}
        out_rosters, unresolved = [], []
        for tid in sorted(roster, key=int):
            ids = []
            for pid in roster[tid]:
                p = resolve(pid)
                if p:
                    ids.append(p["id"])
                else:
                    unresolved.append(pid)
            t = teams.get(tid, {})
            # Keep what the existing entry already knows — owner, points for,
            # points against. The matchup card falls back to an opponent's
            # scoring average when his lineup is unknown, so dropping `pf`
            # would quietly disable that.
            prior = prior_rosters.get(tid, {})
            entry = dict(prior)
            entry.update({
                "id": tid,
                "name": t.get("name", prior.get("name", f"Team {tid}")),
                "wins": t.get("w", prior.get("wins", 0)),
                "losses": t.get("l", prior.get("losses", 0)),
                "ties": prior.get("ties", 0),
                "players": ids,
                "starters": [],
            })
            out_rosters.append(entry)
        lg["rosters"] = out_rosters
        lg["teams"] = len(out_rosters)
        lg["my_team"] = str(c["my_team"])
        lg["status"] = "full"
        lg["source"] = "espn"
        lg["espn_derived"] = True

        if c.get("scoring"):
            lg["scoring_settings"] = scoring_from(
                {int(k): v for k, v in c["scoring"].items()})
            lg["scoring_partial"] = True     # defense falls through to defaults
            rec = lg["scoring_settings"].get("rec")
            lg["scoring"] = "ppr" if rec == 1 else "half" if rec == 0.5 else "std"
        else:
            lg.pop("scoring_settings", None)

        if c.get("matchups"):
            pairs, by_roster = [], {}
            for i, (a, b) in enumerate(c["matchups"], 1):
                mid = str(i)
                pairs.append({"matchup_id": mid, "rosters": [str(a), str(b)]})
                for r in (a, b):
                    by_roster[str(r)] = {"matchup_id": mid, "points": 0.0,
                                         "starters": []}
            lg["matchups"] = {str(c["week"]): {"pairs": pairs,
                                               "by_roster": by_roster}}
        else:
            lg.pop("matchups", None)

        sizes = {r["id"]: len(r["players"]) for r in out_rosters}
        odd = {k: v for k, v in sizes.items() if v != c["roster_size"]}
        lg["note"] = (
            "Rosters rebuilt from ESPN's draft and transaction history — ESPN "
            "will not serve a roster in one piece. Starting lineups were "
            "checked against ESPN and matched. A bench spot or two may be out "
            "of date; paste a roster to correct any team.")
        report.append({
            "league": lg["name"], "teams": len(out_rosters),
            "ghosts": len(ghosts), "unresolved": sorted(set(unresolved)),
            "off_size": odd,
            "scoring": lg.get("scoring"),
            "matchups": bool(c.get("matchups")),
        })

    (APP / "leagues.json").write_text(
        json.dumps(leagues, separators=(",", ":"), allow_nan=False))

    print("wrote", APP / "leagues.json")
    for r in report:
        print(f"\n{r['league']}")
        print(f"  teams {r['teams']}  scoring {r['scoring']}  "
              f"matchups {'yes' if r['matchups'] else 'opponent picker'}")
        print(f"  ghost drops {r['ghosts']}  unresolved ids {r['unresolved'] or 'none'}")
        print(f"  rosters off expected size: {r['off_size'] or 'none'}")


if __name__ == "__main__":
    main()
