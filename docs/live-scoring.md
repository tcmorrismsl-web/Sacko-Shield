# Live in-game scoring

## Two routes, because one of them cannot work

Live updating has to happen where the network is. There are exactly two places
this app can get a live score, and they have opposite failure modes.

**Route 1 — the page's own fetch.** `fetchSleeperLive()` / `fetchEspnLive()`.
Instant, complete, per-player. Works in the downloaded standalone file. Does
**not** work in the published artifact: the capability set a page can be granted
is `artifact, assets, comments, db, downloads, mcp, room, sample, self, user`
and **not one of them fetches a URL** (`mcp` reaches the viewer's connectors,
not arbitrary APIs), and external hosts are blocked besides. Confirmed against
the live capability roster on 2026-10-01, not assumed. No amount of polling
changes it.

**Route 2 — the relay.** A scheduled task reaches Sleeper, and writes the week's
points into the artifact's own `db` store at `live/<league key>`. The page
subscribes with `onSnapshot` and the numbers arrive **with no outbound call at
all.** This is the only way the published artifact shows a live score.

The key property that makes the relay cheap: **writing to the store needs no
republish.** `ArtifactData` writes as the user, so a relay run is one WebFetch
plus one db write — no page read, no publish, no version guard. A republish-based
relay would cost a ~50k-token page read every run and be unusable at any cadence.

## Which route wins

`applyLive()` takes the **fresher** of the two, after checking it is this week's.
Both can be carrying numbers at once and they can disagree — the relay is minutes
old, a direct call is seconds old.

Guards, each of which exists because the failure is silent otherwise:

- **Wrong week is dropped.** A payload left from last week would restate a
  finished week as a live one.
- **Too old is dropped.** `RELAY_MAX_AGE_MS` tracks the relay's real cadence
  (75 min, for an hourly task plus slack). Shorter than the cadence blanks the
  score for most of every hour; much longer still shows Sunday's score on
  Tuesday.
- **Empty is not live.** An all-zero response before kickoff is an empty week,
  and reporting it as live would show every game as finished with no points.
- **Switching league clears everything**, both routes — one league's points
  against another's lineup is worse than no points.

## Cadence

The fastest useful poll is the one the viewer is actually looking at:

| Condition | Interval |
|---|---|
| a game **this matchup depends on** is running, matchup tab open | **15s** |
| that game running, viewer on another tab | 45s |
| no game of theirs in progress | 5 min |
| page hidden | nothing at all |
| after a failure | 15s × 2^n, capped at 5 min |

`myGamesRunning()` is the improvement over "is any game running": it takes the
teams in the two starting lineups and asks only about those. Late in a Sunday
most of the slate involves nobody in the matchup, and polling through it buys
nothing. Falls back to the whole slate when lineups aren't known.

The backoff matters more than it looks. In a published artifact the direct call
is blocked *permanently*, so without it the page would retry a call that can
never succeed four times a minute for as long as it stayed open. The relay keeps
updating meanwhile on its own subscription, independent of the poll timer — which
is why `pollLive()` calls `applyLive()` in its `finally`, not only on success.

`_pollInFlight` stops a slow call stacking a second behind it; four concurrent
`pollLive()` calls make one request.

## The status line must state the age

A number whose age isn't stated reads as instant, and a relayed number never is.
`liveStatus()` renders:

- **direct** — "live", platform, age, and the current checking interval
- **relay, under 3 min** — "live", relayed, age
- **relay, older** — the **age** in place of the live badge, plus "scores as of
  N min ago, and can only have gone up since". A stale relay score is always an
  understatement; points don't come back off. That is what makes showing it
  honest, and showing it without the age dishonest.
- **connected, nothing scored** — projections, with the interval
- **neither route** — says so plainly, names the error, and points at both the
  scheduled refresh and the downloadable file

## The scheduled relay

Two tasks, because one cron expression cannot express both windows:

| Task | Schedule (ET) | Runs/week |
|---|---|---|
| Sacko Shield live scores — Sunday | `7 13-23 * * 0` | 11 |
| Sacko Shield live scores — Thu/Mon night | `9 20-23 * * 1,4` | 8 |

**Hourly is the floor**, not a choice: a 10-minute cron is rejected with
"the minimum interval is 1 hour". Jittered minutes (:07, :09) keep them off the
congested top of the hour. Notifications are off on both — 19 pushes a week
would be noise. Both got automatic approval.

Each run: read `/v1/state/nfl` for the week, read `/matchups/<week>` in the
strict line format, write `live/<league key>` only if something has scored and
something has changed. The prompt pins the document shape, requires a real clock
for `at` (a guessed timestamp silently blanks live scoring via the age guard),
and repeats the standing warning that this relay corrupts ids — copy them
exactly, never substitute a name.

Not yet covered: Saturday games (week 16+) and the occasional Friday game. Add a
third task when the schedule reaches them.

## ESPN

`?view=mMatchupScore&scoringPeriodId=<wk>` carries, per roster entry,
`playerPoolEntry.appliedStatTotal` — and failing that, the `player.stats[]` item
with `statSourceId === 0` (actual, not projected), `statSplitTypeId === 1`, and
the matching `scoringPeriodId`. The same response carries the **real pairings and
each side's actual lineup**, so for ESPN this is the only place the app ever
learns who is really playing whom.

ESPN is **not** in the relay. Its payload truncates over the WebFetch relay (see
`espn-client.md`), so a scheduled run cannot read it reliably. ESPN live scoring
therefore needs the downloaded file, where the browser gets the whole payload.

## The score shown is the platform's, not ours

`booked()` prefers the roster totals from whichever route delivered the points,
then the shipped snapshot's. A starter the database doesn't recognise contributes
nothing to our own sum and would quietly understate the score against the number
in the Sleeper app. Where the two differ by more than a point the card says how
much is unaccounted for rather than papering over it.

## Testing

`test_live.js` — 41 checks, all against stubs, because neither API nor a `db`
server is reachable from the sandbox. Stubbing is the **only** way this path gets
tested at all, the same lesson as `defenses.md`, where three rounds of fixes
passed a 100-check suite while a browser-only path was broken.

It stubs `window.claude.use("db")` with a fake whose `onSnapshot` hands documents
to the test on demand, and covers: the subscription path (`live/<league key>`),
relay points and totals rendering, the age/wrong-week/empty/deleted guards, an
aged payload badged with its age rather than as live, direct beating relay when
fresher, a blocked direct call falling back to the relay rather than to nothing,
the overlap guard, every cadence branch including a game with none of the
viewer's players, the backoff and its cap, the hidden-tab pause, league switching
clearing both routes and releasing the old subscription, exactly one
subscription staying open across repeated switches, and a page with **no** db
capability booting clean and saying so.

One test bug worth remembering: the status line's text spans template-literal
newlines, so `/relayed from Sleeper/` does not match the raw `textContent`.
Normalise whitespace before asserting on rendered copy.
