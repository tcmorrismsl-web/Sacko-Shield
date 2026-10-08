# Points over expected, and the player sheet

## POE — `add_poe.py`

nflverse does not publish `ff_opportunity` for 2026 (every tag 404s), so
expected fantasy points are modelled here from opportunity.

For each position, price one opportunity at that position's league-average
value across all 2026 weekly rows:

```
per_carry   = (0.1·rush_yds + 6·rush_td) / carries
per_target  = (0.1·rec_yds + 6·rec_td + 1·receptions) / targets      # PPR
per_attempt = (0.04·pass_yds + 4·pass_td − 2·int) / attempts
```

Then `xFP = carries·per_carry + targets·per_target + attempts·per_attempt`,
and `POE = actual − xFP`.

**The sample guard matters.** Without it, tight end carries priced at 2.70
points each — two goal-line gadget plays were the entire sample — and any TE
with a carry got a wildly inflated expectation. Anything under `MIN_OPPS = 150`
now falls back to the all-position rate.

Stored per player: `xfp`, `poe`, `poe_g`, `x_rec` (expected receptions), `opps`.
`x_rec` is what lets the app restate POE under half-PPR or standard:

```
POE_scoring = POE_ppr − k·(receptions − expected_receptions)     k = 0.5 / 1.0
```

`poeOf()`, `xfpOf()` and `actualOf()` in the app do that adjustment.

Reading it: positive POE means he is outscoring his volume — likely to fade.
Negative POE with real volume is the buy signal. Through Week 2, Josh Allen was
+17.1/game and DK Metcalf −9.6/game.

## Weekly logs

`logs` used to come from a pivot table filled with zeros, so a week a player
never took a snap looked like a zero-point game — Kyler Murray showed two bars,
one of them a phantom. `played_weeks` now restricts the log to weeks with an
actual stat row, and `logw` carries the real week numbers so the chart can label
them W1, W2 … rather than by array position.

## TE depth goal: 2 → 1

`positionStrength()` scored roster depth as QB 2 / RB 4 / WR 5 / **TE 2**. In a
single-TE lineup the second tight end never starts, so counting him made every
roster look healthier at TE than it was. Now TE 1.

## The player sheet

Any row in the lineup, the waiver board or the player table opens it — rows are
`[data-player]`, keyboard-focusable, with Enter/Space and Escape wired.

Contents: three compact tiles (week projection with its source, per-game, over
replacement), the weekly bar chart, actual-vs-expected with a plain-language
read, then volume and market panels, then injury and matchup notes.

Chart specifics, per the dataviz method: one series so no legend, values labelled
directly because there are few weeks, average as a dashed reference line, a zero
line only when a negative week exists, negative bars in the bad-status color,
`<title>` on each bar for hover, all colors from theme tokens so both themes
work. It says how many games it is drawing when the sample is under four, and
flags a player with no stat line since an earlier week.
