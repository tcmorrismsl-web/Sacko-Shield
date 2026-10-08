# Defenses

## The bug that took four rounds to find

The user reported "no D/ST on my ESPN roster" repeatedly. The shipped data was
correct every time — `leagues.json` had `"MIN"` on his roster, `players.json`
had MIN with a `dst_ctx` and a 7.32 projection, and every local test passed.

The break was in `matchEspn()`, on a code path **this sandbox can never run**.
The sandbox is blocked from ESPN; the user's browser is not. So whenever he
loaded a league from ESPN in the page — via the League sheet, or the "Try
loading from ESPN" button that earlier versions put in front of him — the app
refetched the league and silently dropped every defense.

Why it dropped them:

- ESPN gives a defense a **negative player id**: `-16000 − proTeamId`, so the
  Vikings D/ST is `-16016`. Nothing matches that.
- ESPN names it **"Vikings D/ST"**. `nameKey()` turns that into `vikings dst`.
- The player index only held `min|DST` and `dst min|DST`. **Zero of the 32
  defenses carry an `espn` id at all**, so the id lookup could never work.
- The one fallback tried the first word — `vikings` — which was also absent.

Result: every skill player matched, every defense was discarded, and the roster
came back looking complete with an empty D/ST slot. From outside it looked
exactly like "the defense is missing from my roster."

The same fetch also returned a league with **no `scoring_settings` at all**,
only a `"half"` label, so scoring fell back to `DEFAULT_SCORING`. That is why
the Week tile read "4pt pass TD" instead of "0.5 PPR" — the tell that finally
identified the path, since the shipped data has `scoring_partial: true`.

## The rule now

Defenses are resolved **by team, before anything else, never by name**:

1. `ESPN_PRO_TEAM[pl.proTeamId]` → our team code → `byTeam`
2. failing that, `-id − 16000` → the same map
3. only then names: `vikings dst`, `vikings`, `min dst`, `min`

`espnIndex()` now registers every one of those forms, and keeps a `byTeam` map
so the common path never touches a string.

`tryEspn()` also builds a real scoring table from `mSettings.scoringItems`
using the same certain-only statId map as `build_espn.py`, and sets
`scoring_partial` so the undocumented defensive ids fall through to defaults.

## The guard

If a league starts a DEF slot and a fetch returns rosters with **not one
defense on any team**, the read is refused: `status` drops to
`standings_only`, the note says why, and the "never downgrade" checks upstream
keep whatever is already loaded. A whole position vanishing is a broken read,
not a real roster.

## Testing a path the sandbox can't reach

`test_espn.js` stubs `window.fetch` with payloads shaped like ESPN's —
negative ids, `Vikings D/ST`, `proTeamId`, real `scoringItems` — and runs
`matchEspn()` and the whole `tryEspn()` flow against them. 9 checks, including
two different teams to rule out a coincidence, and the position-loss guard.

**Any browser-only path needs a stub test.** Three rounds of fixes passed a
102-check suite while this was broken, because the suite could only exercise
what the sandbox could reach. "I can't call it from here" is a reason to fake
the payload, not a reason to leave it untested.

## Projection model (unchanged)

D/ST projections come from the opponent's implied total from the betting line,
plus team sack and takeaway rates shrunk toward league average
(2.31 sacks, 1.14 takeaways per game) because two games is a thin sample.
Points-allowed tiers are integrated across the distribution of plausible final
scores (`expectedPaPoints`) rather than read off the mean.
