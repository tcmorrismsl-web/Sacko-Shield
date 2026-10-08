# Pasted rosters

## What it is

ESPN won't serve a roster in one piece (see `espn-client.md`), so the app
accepts a pasted roster: `parseRosterText()` scans arbitrary text for names it
recognises, longest-match-first, masking each hit so a shorter name can't claim
the same characters. Slot labels and team codes are ignored. Defenses match on
city nickname (`vikings`), `MIN DST` and `MIN D ST`.

Saved to `localStorage` **and** to the artifact's own store, read store-first.

## The bug this caused

`applyManual()` used to apply a stored paste **unconditionally on every load**,
overwriting `r.players`. That turned one early paste into a permanent pin:

- the paste is written to browser storage *and* the artifact store, so it
  survives reloads, cache clears and moving between devices
- every later data fix was laid down correctly in `leagues.json` and then
  silently discarded on load
- a paste taken before D/ST could be read kept the D/ST slot empty **forever**

The user reported "no defense" three separate times. Each round the shipped
data was correct and the local tests passed. The defect was entirely in this
override path, and no test that started from a clean browser could see it.

## The rule now

A paste only outranks the shipped rosters when it is **newer than the data
build** (`meta.built`). An older one — including any legacy save with no
timestamp at all — is set aside, not deleted.

- `saveManual()` stamps `savedAt` into both stores
- `loadManual()` returns `{map, savedAt}`, normalising the legacy bare-map shape
  to `savedAt: null` so it counts as older than any build
- `boot()` captures `lg._shipped` before anything is laid over it, so the
  shipped roster is always one tap away
- `rosterSourceBanner()` states which roster the tools are using, on the Week,
  Waivers and Matchup tabs, and offers the other one

Never let stored client state override shipped data silently. If it overrides,
it says so and offers the way back.

## Regression test

`test_stale.js` plants the exact reported state — a legacy bare-map paste with
no D/ST — and asserts:

1. clean browser → D/ST present
2. stale paste → shipped rosters win, D/ST still present
3. stale paste is offered back, not dropped
4. a paste newer than the build still takes effect
5. it says so, with a one-tap way back
6. tapping it restores the defense

Run it alongside `test.js` on any change to roster loading. A clean-browser
test alone would have passed throughout the entire bug.

## Bumping `meta.built`

Rebuilding league data means bumping `built`, otherwise a paste made between
the last build and now still outranks fresh rosters. `build_espn.py` changes
rosters, so a `built` bump belongs with it.
