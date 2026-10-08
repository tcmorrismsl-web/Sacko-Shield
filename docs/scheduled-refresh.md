# The scheduled refresh — what it can and cannot do

## The blocker is NOT absolute — 2026-10-01 corrects this

For two runs (09-23, 09-29) a scheduled run had **no path to Sleeper at all**.
`WebFetch` against `api.sleeper.app` returned:

```
PROVENANCE_REQUIRED — the permission request for this URL was not answered in time
```

**On 2026-10-01 that prompt did not fire.** A scheduled run reached
`api.sleeper.app` on every call it made: the league object, `/rosters`,
`/users`, `/matchups/4`, and the five `projections/nfl/2026/4` position pulls.
All returned real data.

So the rule is now: **try Sleeper every run, and only fall back to the model
when it actually refuses.** Do not assume the block. The carry-forward path and
the model-stat-line path below are still needed, and still correct when the
refusal does come back — but a run that assumes a refusal it never got ships a
model number where a real projection was available, which is the whole error the
app exists to avoid, arrived at by being pessimistic instead of lazy.

What each step produced on 2026-10-01:

| Step | Result |
|---|---|
| Sleeper projected stat lines (`pstats`) | **256 feed lines** (QB 32, RB 72, WR 74, TE 46, K 32) |
| Sleeper league rosters | **269 slots, 10 rosters, all five checks passed** |
| Sleeper `scoring_settings` | **re-read, 44 keys, no material change** |

Everything else — DynastyProcess, nflverse, the schedule, the betting lines —
comes from `raw.githubusercontent.com` and `github.com` release assets over
plain curl and refreshes normally.

## Two relay failure modes, both confirmed on 2026-10-01

`leagues.md` already records that **player ids get corrupted** and that names
survive. Two more, found this run:

1. **The TEAM field on a projection line can be wrong.** The WR feed returned
   `Marvin Harrison|TEN`. Four independent sources — nflverse `roster_2026`
   week 4, nflverse weekly stats for weeks 1–3, DynastyProcess `values.csv` and
   the FantasyPros weekly feed — all say **ARI**. He appears in the feed
   immediately after three genuine TEN receivers, so the relay most likely
   carried a neighbouring line's team across.
   **So: match on name + position only, never on team, and never write the
   feed's team back.** Overwriting it also desyncs `opp`, `home` and `bye`,
   which are derived from the schedule. `add_pstats.py` now reports the
   disagreement and keeps the database's team.
2. **The `COUNT=` footer is unreliable.** It came back inflated or deflated on
   almost every call this run — RB said `COUNT=88` above 73 lines, WR said
   `COUNT=108` above 76, the rosters said `TOTAL=273` for 269 actual slots, the
   QB feed said `COUNT=31` above 32 lines. The footer is the summarising model's
   own arithmetic and cannot be trusted.
   **What IS trustworthy is a per-element count.** Every roster's `N|<id>|<n>`
   line matched the real length of its own `P|` line exactly; a truncated list
   would disagree with its own count. Ask for a count per element, not just a
   total, and verify it yourself.

## Detecting the upcoming week

`upcoming_week` is **the first week in which most games are still unplayed.**

The obvious rule — first week with no scores at all — breaks mid-week, and it
broke in both directions inside one run that spanned three days:

| When | Week 3 state | "no scores" says | Right answer |
|---|---|---|---|
| Sun 09-27 09:19 ET | 1 of 16 final (Thu game) | week 4 | **3** — fifteen games still to play |
| Mon 09-28 14:02 ET | 15 of 16 final | week 4 | **4** — only MNF left |

On any run made between Tuesday and Thursday a week has either no scores or all
of them, so the majority rule and the literal rule agree. They differ only
mid-week, and only in the direction of keeping whichever week the bulk of the
slate still lies ahead in. `completed_week` is then `upcoming_week - 1`, even if
one game of it is outstanding; `meta.week_note` names the teams whose game had
not kicked off, because their players show one game fewer until the next run.

On 2026-10-01 (a Thursday, the PIT@CLE opener not yet played): week 3 is 16/16
final, week 4 is 0/16, upcoming week **4**, no outstanding games. Betting lines
run through **week 5**, so every defense has a market projection.

## Detecting the weekly feed's lag

`fp_latest_weekly.csv` re-scrapes daily and still lagged a week on 09-29. Its
scrape date is not evidence. Detect coverage by **matching its stated opponents
against the real schedule**: on 2026-10-01, 651 of 652 rows matched week 4, so
`weekly_covers_week = 4 = upcoming_week` and the UI trusts its grades, ranks and
`wk_proj` — including as a model baseline, which is only allowed while the two
are equal.

## The carry-forward guard, and the model stat line

`carry_pstats.py` carries the previous build's `pstats` forward and **refuses to
if the week has moved on**:

```python
if pmeta["proj_week"] != meta["upcoming_week"]:
    # ship none, and say so
```

Refusing is right, but refusing alone used to break the app's whole reason for
existing: with no `pstats`, `pj()` falls back to the shipped PPR `proj`, so
every skill player is priced at 4 points a passing touchdown no matter what the
league pays.

So the model does not emit points either. **It emits a stat line.** For each
player, take his own per-game stat shape (his `sstats` over the games he has
played, or his position's average shape when he has none) and scale it so its
PPR value equals the model's projection. The line is keyed by Sleeper's scoring
names like any other, so the league multiplies it directly and a 6-point passing
touchdown bites.

`pstats_src` distinguishes them (`"model"` / `"sleeper"`), and `projExact()` in
the app requires `pstats_src !== "model"`, so a model line still carries its `~`
marker. Both kinds score through this league's own table — that is what storing
lines rather than points buys, and it holds however the line was made — but only
a feed's line is a projection, and the UI must never read as if the two were the
same thing. 234 model lines on the 2026-10-01 build, against 256 feed lines.

## The model curve

Without a feed the baseline comes from production, which needs handling:

- **x-axis is consensus ROS rank, y-axis is actual points per game.** Reading
  PPG off directly puts one big game on whatever rank that player holds and
  reports it as what every player at that rank is worth — which is how a backup
  quarterback ends up projected fourth at the position.
- A local mean over ±4 ranks, blended 50/50 with a log-linear least-squares fit,
  then forced monotone.
- **Then regressed toward the startable-tier mean** by `games/(games+2)`.
- `form` is capped at ±15% (not ±30%) when the curve is built from this season's
  production, because the production signal is already inside the curve.
- `wk_proj` is only allowed as a baseline while `weekly_covers_week ==
  upcoming_week`.

## The id bug that swallowed nine kickers

Players with no Sleeper id got a synthetic id built from their FantasyPros id.
When that field is the literal string `NA` — which it is for every kicker in
`values.csv` — every one of them collapsed onto the single id `fp-NA`, and the
database held **30 kickers instead of 39**. Trey Smack was the visible symptom:
`id: "fp-NA"`.

Synthetic ids now fall back to the name (`nm-trey-smack`) whenever the source id
is missing or `NA`. Check `len(set(ids)) == len(ids)` after the build; a
collision is silent otherwise and looks like a thin position, not a bug.

The same fix let an older placeholder resolve: the 14-team league carried `k_trey_smack` on
another team's roster from a session where he existed in no id source.
`build_leagues.py` now repairs `k_*`/`p_*` placeholders by name when the real row
exists, and records it in `meta.league_verification.placeholder_ids_repaired`.

## The league gate

`verify_league.py` keeps the previous `leagues.json` but still runs every
structural check against the **rebuilt** player database before shipping it:
10 rosters, no player on two rosters, no duplicates within a roster, every
starter rostered, ≥95% of ids resolving. A roster that no longer resolves is
worse than no roster. 268/269 = 99.6% on 10-01; the one miss is Sleeper id
`13602`, which appears in no id source at all and sits on another team's bench —
the same single miss as 09-23, 09-27 and 09-29.

A run that reaches Sleeper **can** see a waiver claim, a trade, a lineup change
and a commissioner's scoring change. The 10-01 run caught twelve roster slots
changing league-wide since the 09-23 snapshot, four of them on Tyler's team.
A run that is refused cannot, and cannot confirm that one *hasn't* changed
either, which is worth saying plainly rather than reporting "unchanged".

## Rebuild order

```
build_schedule.py → build_players.py → add_dst.py → add_poe.py
  → add_pstats.py → add_kickers.py        (when Sleeper answers)
  → carry_pstats.py                      (when it refuses and the week hasn't moved)
  → add_model.py → add_variance.py → finalize.py
  → build_picks.py → build_leagues.py → build_meta.py
```

`add_kickers.py` must follow `add_pstats.py`; it appends rows that would
otherwise be overwritten. `add_model.py` fills only players `add_pstats.py` and
`add_kickers.py` left without a line. `finalize.py` recomputes `proj` as the PPR
score of the stored stat line, so the fallback number and the league-scored
number can never disagree about who is better, and derives the shipped
`replacement` table.

## Testing a republish, and the view guard

`test.js` serves the **authored** page — the published copy with claude.ai's
injected skeleton stripped, then re-wrapped — with the rebuilt data as real
siblings, and clicks through every tab in every league. 121 checks on 10-01, at
1280px and 390px, then re-run against the **downloaded published files** and
passed again, with all five hashes matching the local build.

The published page carries claude.ai's skeleton on line 1 (`<!doctype html>…
<body>`) and the last line (`</body></html>`); a republish must strip both, or
the page gets double-wrapped. Line numbers shift as the file grows — assert on
the content, not on a line number.

**The publish view guard resets on every `read`.** A publish is refused unless
the live version has been Read in full, and calling `action: "read"` again
re-saves the file and **clears the lines already read**. So: read the saved file
end to end in contiguous `Read` calls with **no `action: "read"` in between**,
then publish. The refusal footer tells you which lines are still outstanding
(`you have not yet Read lines 1001-3714`) — use it rather than guessing. Two
publishes were refused this run before that was understood.
