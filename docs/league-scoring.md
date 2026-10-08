# League scoring — the app's most important correction

## The problem

Every public projection is expressed in points under *somebody else's* scoring.
Sleeper's `pts_ppr` assumes 4 per passing touchdown and 0.04 per passing yard.

The Sleeper dynasty league pays **6 and 0.05**. It also pays −2 per interception and
sets every D/ST points-allowed tier 3 points above the common default
(0 → 12, 1–6 → 10, 7–13 → 7, 14–20 → 4, 21–27 → 1), and scores forced fumbles.

The effect, Week 3:

| Player | Default scoring | This league | Diff |
|---|---|---|---|
| Jared Goff | 20.0 | 27.2 | +7.2 |
| Patrick Mahomes | 21.8 | 28.2 | +6.4 |
| Lamar Jackson | 24.2 | 29.9 | +5.7 |
| Bijan Robinson | 20.4 | 20.4 | 0.0 |
| SEA D/ST | 7.6 | 9.7 | +2.1 |

Quarterbacks gained five to seven points each and skill players didn't move. In
a superflex league starting two quarterbacks that is roughly **12 points a week
of systematic error** — enough to invert a start/sit call and to misprice every
quarterback on the waiver wire.

## The fix: store stat lines, not points

`add_pstats.py` stores the projected **stat line** (`pstats`) rather than a
points total, and the app multiplies it by whatever the league pays. Season
production is stored the same way (`sstats`) so the season can be restated too.

Keys use Sleeper's own `scoring_settings` names — `pass_yd`, `pass_td`, `rec`,
`rec_yd`, `sack`, `int`, `pts_allow_7_13` … — so a league's settings object
multiplies against a stat line with no translation table:

```js
function scoreLine(stats, sc) {
  let t = 0;
  for (const k in stats) if (typeof sc[k] === "number") t += stats[k] * sc[k];
  return t;
}
```

## Partial settings must merge, never replace

ESPN surfaces a league's reception value without `mSettings` but nothing else.
Scoring a stat line against `{rec: 0.5}` alone valued Lamar Jackson at **zero** —
caught in testing. `scoringOf()` now layers a league's known values over
`DEFAULT_SCORING`, and the provenance card states which case applies:

- full settings → "computed against this league's own scoring", with the values named
- partial (ESPN) → "ESPN gave up the reception value but not the rest"
- none (the 10-team ESPN league) → "standard scoring — treat as a guide, not this league's numbers"

## D/ST

`pj()` computes a defense from `dst_ctx` against the league's own tier values,
integrating a normal(implied, 9.5) across the tier boundaries rather than taking
the tier of the mean. Season D/ST points are rebuilt from `pa_log` the same way.

## What still approximates

- **POE** is computed in PPR upstream and restated only by the reception gap.
  The rest of the scoring cancels, since both sides of `actual − expected` use
  the same rates — but a league with unusual yardage values would shift it
  slightly.
- **The weekly game-log chart** scales the shipped PPR log by the ratio of
  restated season points to shipped season points, rather than rebuilding each
  week from its own components. Per-week stat lines would fix this.
- **Kickers** have no stat line at all; they ride the positional curve.
- Bonus scoring (100-yard games, 40+ yard touchdowns, TE premium) is not
  modelled. The Sleeper dynasty league has none of these; a league that did would
  need its own handling.

## Refreshing

`add_pstats.py` reads pipe-delimited feeds from `/home/claude/feeds/{qb,rb,wr,te}.txt`,
fetched from Sleeper's projections endpoint one position at a time, with player
**ids excluded** and names matched — see `leagues.md` for why ids can't be
trusted over that relay. The scheduled refresh does not yet rebuild these; it
still overlays `pts_ppr`. Re-running `add_pstats.py` by hand is what keeps the
league-scoring path current.
