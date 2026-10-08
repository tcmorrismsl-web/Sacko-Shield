# Which week it is

## What went wrong (Oct 2, 2026)

Tyler: "Not pulling current week, showing LY in the matchup data and projections."
Four independent causes, each verified before anything was changed:

1. **The downloaded file was frozen on Week 3.** It bakes its data in, never
   updates, and — after the Oct 1 changes moved the boot block — could not even
   be rebuilt (`build_standalone.py` failed on its `capabilities` anchor). The
   claude.ai page had no league-switch write from him since Sep 23, which points
   to the file being what he opened.
2. **Hand-picked ESPN opponents weren't tied to a week.** `manual_opponent`
   carried over, so a Week 3 pick was shown as the Week 4 opponent.
3. **Picking an opponent saved every roster in the league** alongside it, which
   reloaded as a paste and put "Working from the roster you pasted in" on screen
   when nothing had been pasted.
4. **Kickoffs were 4 hours early.** The Oct 1 rebuild wrote `games.csv`'s Eastern
   wall clock with a `Z`. Thursday 8:15pm ET became 20:15Z (4:15pm ET), so the app
   could call games final before they started.

Plus one false promise found while fixing the tests: an ESPN league's live-score
line said the scheduled refresh "writes live scores here." The relay only covers
the Sleeper league.

## How the app decides now

- `dataWeek()` — `meta.upcoming_week`, the week the data was built for.
- `clockWeek()` — from `schedule.json` kickoffs: the first week whose last game
  hasn't ended (`end` = kick + 190 min). A week lasts until Monday night's game
  is over.
- `staleWeek()` — the clock week, when it's later than the data week.

When stale: a banner on every tab ("Week N is over — it's Week M now…"), the
matchup tab shows no game at all rather than last week's as current, and live
polling stops (polling a finished week fetches last week's finals). The banner's
remedy differs by copy: the published page points to the next scheduled
rebuild; the downloaded file says it never updates itself.

Opponent picks are stored with `__opponentWeek` and used only in that week. A
pick with no week (saved before this change) is never reused. Only rosters that
differ from the shipped ones are saved as a paste.

## Data rules (also in the refresh task's instructions)

- **Kickoffs are converted America/New_York → UTC with zoneinfo**, never a fixed
  +4: DST ends Nov 1, 2026. Check: every non-Thanksgiving Thursday game lands at
  00:15Z (01:15Z after Nov 1) on Friday. Thanksgiving's 1pm and 4:30pm games are
  the only legitimate Thursday daytime kickoffs. `fix_kickoffs.py` does this,
  cross-checks each stored time against games.csv, refuses on disagreement, and
  is idempotent.
- **`upcoming_week` = earliest week with any game lacking a final score.** A week
  whose Thursday game is scored but whose Sunday games aren't is still the
  current week. A literal reading of "first week with no scores" would advance a
  week early every Sunday morning. Cross-check Sleeper's `state/nfl` week.
- **No ESPN pairings from the relay.** Two reads of the half-PPR ESPN league's Week 4 schedule
  disagreed (team 3 vs 6, then team 3 vs 5 *and* team 1 vs 5 — impossible).
  The app asks for the ESPN opponent each week; the downloaded file reads real
  pairings from ESPN in the browser.

## Tests

`test_week.js` (20 checks) pins the clock with a `Date.now` offset: mid-week,
5 minutes either side of the last game ending, after the week turns, a Week 3
copy opened in Week 4, and every opponent-pick case. Run against the
previously published page it fails exactly where the bugs were — which is the
point of a regression test. `test_live.js` and `test_stale.js` were themselves
pinned to Week 3 (fixtures and a tab labelled "Week 3"); both now derive the
week from the data or select tabs by role.

**Rule: nothing — code, fixtures or tests — may hardcode a week number.**
