# Reading ESPN

## The problem

ESPN will not serve a fantasy roster in one piece. `view=mRoster` embeds a full
season of stats inside every player entry, so the response is cut off after
about six players — and `forTeamId` doesn't help, because the truncation is on
total payload size, not team count. Several rounds were lost to this: the app
kept shipping a *paste your roster* box as a workaround, which from the user's
side was the same empty screen with a form in front of it.

## What actually works

Four views come back **complete**, because they carry bare ids instead of
player objects:

| view | gives | size |
|---|---|---|
| `mDraftDetail` | every pick as `teamId → playerId` | complete at 224 picks |
| `mTransactions2` | every add/drop in a recent window | complete |
| `mSettings` | lineup slots + full scoring table | complete |
| `mTeam` | team names, records, points for | complete |

So a roster is **reconstructed**: draft, then executed `ADD`/`DROP`
transactions applied in `proposedDate` order. `LINEUP` and `ROSTER` items are
skipped — they move a player between starting and bench, not between teams.

`mSettings` returned 401 on earlier attempts and 200 later, so a refusal is
worth retrying rather than treating as permanent. The 10-team league still refuses it.

## Defenses

D/ST arrive as **negative player ids**: `-16000 − espnProTeamId`. So `-16014`
is the LAR defense, `-16023` is PIT. This is what finally put a D/ST on the
user's ESPN rosters — the thing he reported broken three times.

## Identity

Player ids resolve through `players.json`'s own `espn` field, with
DynastyProcess `db_playerids.csv` as a fallback crosswalk. Coverage was
119/119 on the first league with zero misses.

The relay that returns WebFetch results has corrupted ids in the past, so this
was verified end to end rather than assumed: for one team, the ids from
`mMatchup`, the picks from `mDraftDetail`, and the **names** from `mRoster`
were compared against each other and against `players.json`. All four agreed.
That check is the reason the ids can be trusted.

## Known limit: the transaction window

`mTransactions2` only reaches back a few weeks, not to the draft. A player
acquired *and* still held during that gap is missed; a drafted player released
during the gap is still shown. This surfaces as a **ghost drop** — a `DROP` for
someone never on our copy — and leaves rosters 1–2 over the expected size.

Measured: 6 ghosts in the 8-team league, 6 in the 14-team, 9 in the 10-team; most teams land within one
or two of the right count. The error is confined to the bench.

Verification: for the two teams ESPN would return names for, **all six live
starters were present** in the reconstruction. Starters are what start/sit and
the matchup card depend on, so that is the part that had to be right. The note
on each league says plainly that a bench spot may be stale, and pasting a
roster still overrides everything.

## Scoring

Only ESPN statIds whose meaning is certain are mapped (offense and kicking).
ESPN's defensive stat ids are undocumented; guessing one wrong would silently
misprice every defense, so the defensive half is deliberately left out and
`scoring_partial` lets it fall through to `DEFAULT_SCORING`.

Confirmed from `mSettings`:

- **8-team ESPN league** — `53: 0.5` → half PPR, 4 per passing TD, 0.04 per passing yard
- **14-team ESPN league** — `53: 1.0` → full PPR, otherwise the same shape
- **10-team ESPN league** — `mSettings` 401s, so defaults stand and the source card says so

The half-PPR league being half PPR is not cosmetic: it moves Puka Nacua from 17.05 to 14.1.

## Matchups

Pairings live in `mMatchupScore`, which truncates before reaching later weeks —
the 8-team half-PPR league yields 2 of 4 week-3 games, the 14-team PPR league yields none. Whatever
arrives is baked in; where the user's own team isn't covered, the matchup tab
falls back to a one-tap opponent picker that persists.

A pairing can be known while the lineup behind it isn't, so each side falls
back to its best available lineup rather than rendering an empty team.

## Rebuilding

`build_espn.py` reads `/home/claude/espn/*.txt` (pipe-delimited pulls) plus
`leagues_cfg.json`, and rewrites the ESPN entries in `leagues.json` in place,
preserving `owner`, `pf` and `pa` from the existing entry — `pf` drives the
matchup card's fallback when an opponent's lineup is unknown.
