# Sacko Shield

Fantasy football assistant for Sleeper and ESPN leagues (redraft, keeper, dynasty):
start/sit, waivers, trades, matchup simulation with live scoring, player analysis,
league analyzer, Excel export.

The live app is published as a claude.ai artifact and refreshed by scheduled tasks.
This repo is a snapshot of that published version (Week 5 data, built Oct 8, 2026).

## Layout

| Path | What it is |
|---|---|
| `app/index.html` | The app (the artifact page, without claude.ai's injected `<html>/<body>` wrapper) |
| `app/data/*.json` | Players, schedule/kickoffs, picks, build metadata (`leagues.json` is local only, see below) |
| `pipeline/` | Python build scripts that produce `app/data` (order below) |
| `pipeline/espn/` | Local only: ESPN draft/transaction pulls and `leagues_private.json` (league IDs, standings) |
| `tests/` | Playwright suites; `head.txt` is the head claude.ai injects |
| `docs/` | Design notes: why things work the way they do, and the bugs behind them |

## Private league data (not in this repo)

Manager names, team names and league IDs are kept off GitHub. These paths are in
`.gitignore` and exist only on your own computer:

- `app/data/leagues.json` — every league's teams, managers and rosters
- `pipeline/espn/` — ESPN pulls plus `leagues_private.json`, which
  `build_leagues.py` reads for each ESPN league's ID, name and standings
- `docs/leagues.md` — the league-by-league notes

A fresh clone has none of them, so the app shows no leagues until the pipeline
rebuilds `leagues.json` (or you copy it in). Tests find leagues by shape (source
and scoring), not by ID, so they work against whatever local file you have.
Before committing, `git status` should never list any of the files above.

## Public test page (GitHub Pages)

`index.html` at the repo root is the standalone app built **without any league
data**: it ships one placeholder league ("Connect your league") with generic team
names. Open the Pages URL, tap **League**, and load a Sleeper or ESPN league by ID.
That league is saved in your browser only (localStorage), never in this repo.

**Personal link.** In the League panel, pick your team in each league, then tap
**Copy my link**. The link looks like `…/Sacko-Shield/#leagues=s:<id>:<team>,e:<id>:<team>`
(`s` = Sleeper, `e` = ESPN). Opening it on any device loads those leagues live,
selects your team in each, and saves them in that browser, so bookmark it or add
it to your home screen. The part after `#` is never sent to GitHub. Your team is
remembered per league.

Rebuild it after changing `app/index.html`:

```
python3 pipeline/build_standalone.py --app app --out index.html --public
```

`--public` swaps in the placeholder league, drops league-specific notes from
meta, and refuses to write the file if any name or ID from your local
`leagues.json` would end up in it.

## Pipeline order

```
build_players.py → apply_sleeper_proj.py → add_poe.py → add_dst.py
→ add_pstats.py → add_kickers.py → add_variance.py → add_matchups.py
→ build_leagues.py → build_espn.py → fix_kickoffs.py → build_standalone.py
```

`build_standalone.py` turns `app/index.html` into one self-contained HTML file
with the data inlined. That file can be opened from disk or hosted anywhere
static (GitHub Pages works), and unlike the artifact it can call Sleeper/ESPN
directly for live scores.

## Known limits of this snapshot

- **Paths are absolute.** Scripts and tests still point at the original build
  workspace (`/home/claude/...`, `/mnt/user-data/outputs/...`). They need those
  paths changed to repo-relative ones before they run from a fresh clone.
- Raw upstream inputs (nflverse CSVs, DynastyProcess, Sleeper feed pulls) are not
  included; the scripts download or expect them.
- Tests: `npm i playwright` then `node tests/test.js` (and the other suites),
  once paths are fixed.

## Rules the code follows

- Nothing hardcodes a week number. Current week comes from `meta.upcoming_week`
  and the kickoff clock (`docs/current-week.md`).
- Kickoffs are stored in UTC, converted from US Eastern with real DST rules.
- Projections are stored as stat lines and scored with each league's own settings.
