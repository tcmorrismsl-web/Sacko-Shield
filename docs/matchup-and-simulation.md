# The live matchup tab

One simulation drives the score, the win probability and the path to victory,
so the three can never disagree with each other.

## Variance — measured, not assumed

`add_variance.py` pools every player's own weekly spread by position. Two games
each is thin individually; pooled across hundreds of players it is usable.

| Pos | n | CV | sigma model |
|---|---|---|---|
| QB | 33 | 0.36 | 4.41 + 0.102·mean |
| RB | 67 | 0.49 | 1.05 + 0.355·mean |
| K | 32 | 0.47 | 0.50 + 0.404·mean |
| WR | 114 | 0.64 | 1.53 + 0.378·mean |
| DST | 29 | 0.64 | 1.61 + 0.391·mean |
| TE | 56 | 0.74 | 1.22 + 0.472·mean |

Quarterbacks move least, tight ends most — which is what the position is known
for, arrived at from this season's data rather than assumed. Kickers carry
per-week stat lines rather than points, so they are scored against one reference
table purely to measure movement; without that they inherited the TE model and
looked twice as volatile as they are.

## The simulation

20,000 runs. Each player is drawn as `banked + max(0, remainingMean + sigma·Z)`,
where `remainingMean` is his league-scored projection times the share of his
game still to play, and sigma shrinks by `sqrt(share remaining)` — a player with
ten minutes left can't swing the way one at kickoff can.

**Seeded** with mulberry32, hashed from the state being simulated. The same
matchup gives the same answer on every repaint; a score or lineup change moves
it. Before seeding, the number jittered about a point between renders, which
displayed sampling noise as precision. It is also rounded to a whole percent for
the same reason: at n=20,000 the standard error near 50% is about 0.35pp.

## Path to victory

Not "he could go off" but the **conditional expectation given a win**: across
the runs where you win, what did each of your players actually average? The
levers are sorted by how far that exceeds their ordinary mean. That is the shape
of a realistic win rather than a best case.

Four endgame states are handled explicitly, because the generic version said
"every game is over" while games were still running:

- **nothing left to play** → the final margin
- **zero wins in 20,000** → says plainly it's gone, with the deficit and what's left
- **all 20,000 wins** → says it's yours and whether they have anything left
- **no lever clears the threshold** → says it comes down to spread, not one player

## Live scoring

Only the standalone can do it — the artifact sandbox blocks the call, and the
matchup card says so rather than pretending.

`pollLive()` reads Sleeper's `/matchups/{week}`, which carries each roster's
running total and every starter's points. Polling is 45s while a game is running
and 5 minutes otherwise, paced off `gamesRunning()` against the kickoff table.

**The guard that matters**: a live feed is only claimed once something has
actually scored. An all-zero response before kickoff is an empty week, not live
data, and treating it as live would mark every game finished with no points —
turning a full lineup into zeros.

`gameState()` likewise reports every game as pre-kickoff when there is no live
feed, whatever the clock says. Without scoring attached, a game the clock calls
over has no points, and calling that "final" would be a lie.

## Kickoff times

`add_matchups.py` converts `gameday` + `gametime` from games.csv (US Eastern) to
UTC with a 190-minute wall-clock window, stored per team per week in
`schedule.json` under `kickoffs`. Matchup pairings and week-specific starters —
which can differ from a roster's stored `starters` — go into `leagues.json`.

## The refresh bug — `mergeLeague()`

**Reported as "matchup tab says there are no head-to-heads."** The standalone's
`refreshSleeper()` replaced the league object wholesale with what `trySleeper()`
returned, and `trySleeper()` supplied neither `matchups` nor `scoring_settings`.

The missing matchups were the visible half. The invisible half was worse: the
league silently reverted to `DEFAULT_SCORING`, so a league paying **6 per
passing touchdown dropped to 4** with nothing on screen to say so. Every
quarterback lost five to seven points and the app looked like it was working.

Two changes:

1. `trySleeper()` now stores `scoring_settings` from the league payload (it was
   always in the response, just discarded) and fetches `/matchups/{week}`, so a
   refresh makes both *fresher* rather than absent.
2. `mergeLeague(prev, fresh)` carries forward anything a fetch can't supply —
   `scoring_settings`, `scoring_partial`, `note`, `platform`, `type`, `season`.
   Matchups are week-keyed and only carried forward when they still cover the
   week being displayed, because a stale pairing is worse than none.

Applied at every point a league is replaced: `refreshSleeper`, `loadEspnInline`,
and both connect-sheet handlers. The regression suite asserts a merged league
keeps `matchups` and `pass_td === 6`.

## The streaming board — `renderStreamBoard()`

**Reported as "still no D/ST for ESPN leagues."** The defenses were there — in
the Players tab. The Waivers tab, where anyone would actually go to stream one,
showed the "needs this league's rosters" card for all three ESPN leagues.

Ranking a defense or kicker for streaming doesn't need anyone's roster. It needs
this week's matchup and this league's scoring, both of which are in hand. What
is genuinely missing is who is free — so `own` (rostered percentage across all
leagues) stands in, and the card says that is what it is.

**Grouped by position, defenses first.** Pooling into one ranking buried all 32
defenses below all 32 kickers, because kickers outscore defenses on raw points —
the opposite of useful when the point is choosing one of each.

## Week 3

Your team (1-1) vs. the opponent (2-0, the league's highest
scorer). 162.0 projected against 157.2, **56%**.

## Regression suite

Run against both builds: boot, six tabs × four leagues, scoring spot-checks per
league (pass TD, Lamar, top kicker, top defense), format isolation, the matchup
tab rendering a real head-to-head where rosters exist, D/ST rows present on the
waiver tab where they don't, the `mergeLeague` guard, horizontal overflow and
console errors. Plus live-state injection at mid-slate and a late trailing
position. All passing.
