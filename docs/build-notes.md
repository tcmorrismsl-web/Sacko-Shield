# Build notes

## The rule that was broken, and how

For several rounds the app "passed every test" while the user reported it
broken. The cause was not a code bug — it was **testing the wrong artifact**.

Tests ran against `/home/claude/app/` served through a hand-made preview
wrapper. The user opens the *published* artifact on claude.ai. Those two had
silently diverged:

- the published `index.html` was **ahead** of the local source (a fix existed
  live that the local copy had lost)
- the published `data/meta.json` was **richer** than local (variance,
  replacement levels and the league verification block were missing locally)
- the published `data/leagues.json` still had `status: "standings_only"` and
  `players: []` for every ESPN team

That last one was the whole reported failure. The ESPN rosters were empty in
the copy he was opening, and no local test could ever have seen it.

**Rule: before testing, pull the published files and test those.**
`Artifact action:"read"` returns the served `index.html`; `action:"list"` with
`scope:"files"` lists the data files; `action:"read"` with `paths` downloads
them. Reconcile local against published *first*, then build, then test.

## The test harness

`/home/claude/test.js` drives both builds:

1. the artifact page reassembled with the **exact head claude.ai injects**,
   data files served as real siblings
2. the standalone, opened from disk

It clicks tabs rather than calling render functions, because a handler that was
never wired still "passes" when the test calls the function behind it. 102
checks: every tab × every league, D/ST and K present on ESPN rosters, position
chips matching `gradedPositions`, both matchup paths (known pairing and
opponent picker), per-league scoring actually biting, no console errors, no
horizontal overflow at 390px.

Blocked `api.sleeper.app` requests are scoped out **by name** — the sandbox
proxy blocks that host and the app handles it — but every other console error
still fails the run.

One harness bug worth remembering: top-level `const S` in a classic script does
**not** attach to `window`, so `window.S` is undefined while bare `S` resolves.
A probe on `window.S` hangs forever and looks exactly like a boot failure.

## Pipeline order

```
build_players.py → apply_sleeper_proj.py → add_poe.py → add_dst.py
→ add_pstats.py → add_kickers.py → add_variance.py → add_matchups.py
→ build_leagues.py → build_espn.py → build_standalone.py
```

`add_kickers.py` must follow `add_pstats.py` (it appends rows that would
otherwise be overwritten). `build_espn.py` runs after `build_leagues.py`,
since it edits the ESPN entries in place.

`build_standalone.py` is an anchor-based string transform of the artifact
source; it raises `SystemExit` naming the missing anchor if the source moves,
so a silent stale build isn't possible.

## Publishing

A publish is refused unless the live version has been read in full this
session. That guard is correct and caught a real divergence here — do not work
around it. Read the saved source, merge onto it, publish from the merged file.

Data files left out of a publish are **kept**, so only changed ones need
sending.

## Standing corrections

- Injury reports are a **flag**, never a multiplier. A stale report once
  projected a healthy Kyler Murray at 1.84 against Sleeper's 18.45.
- A partial scoring table must sit **on top of** `DEFAULT_SCORING`, never
  replace it. `{rec: 0.5}` alone scores every quarterback at zero.
- `refreshSleeper()` must merge, not replace: dropping `scoring_settings`
  reverted a 6-point-passing-TD league to 4 with nothing on screen to say so.
- Un-played weeks are not zero-point games (`played_weeks` + `logw`).
- Win probability is seeded (`mulberry32`) so it doesn't twitch between
  repaints, and rounded to a whole percent because the sample supports no more.
