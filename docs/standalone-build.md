# The standalone HTML build

`build_standalone.py` turns the Artifact page into one self-contained file at
`/mnt/user-data/outputs/sacko-shield.html` (~720 KB, ~150 KB gzipped).

It is a **transform of `app/index.html`, not a fork.** It applies a list of
exact-string swaps and raises `SystemExit` naming the missing anchor if the
source moved. So edit `app/index.html`, then re-run the build — never edit the
standalone by hand, or the two drift.

## What changes leaving claude.ai

| Concern | Artifact | Standalone |
|---|---|---|
| Document skeleton | supplied at publish time | written by the build |
| Data files | `fetch("data/*.json")` siblings | inlined `<script type="application/json">` |
| Excel download | `downloads` capability | Blob + `<a download>` |
| Saved state | `db` + `user` capabilities | `localStorage` |
| Sleeper API | blocked by artifact CSP | **works — page refreshes itself** |

Inlined JSON has `</` escaped to `<\/` so a string can't close the script tag.

## The one real gain

No CSP, so `trySleeper()` actually runs in the browser. `refreshSleeper()` fires
on every load, re-pulls every Sleeper league it knows about, and preserves the
selected team by matching on team *name* across the refresh (roster ids can
shift). Failures are swallowed — the baked-in snapshot keeps working offline.
Leagues the viewer connects themselves persist in `localStorage` under
`sacko.leagues`.

This means the standalone is the better copy for the Sleeper league, and the
Artifact is the better copy for sharing and for Claude-side updates.

## Hosting

Static host, no build step, no server: GitHub Pages, Netlify drop, S3, or
`file://` straight off disk. Two external requests — Google Fonts and SheetJS
from cdnjs. Both degrade: fonts fall back to the declared stack, and a blocked
SheetJS now shows "The spreadsheet library didn't load" instead of failing
silently. To make it fully offline, inline `xlsx.full.min.js` and drop the font
link.

## Refreshing the data

Re-run `build_players.py` → `apply_sleeper_proj.py` → `build_leagues.py`, then
`build_standalone.py`. The scheduled task does the first three and republishes
the Artifact; it does **not** rebuild this file — regenerate it when you want a
current standalone copy.
