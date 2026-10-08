# Format isolation, and kickers

## Why formats must not mix

A dynasty value and a redraft value answer different questions. Dynasty asks
what a player is worth to own for years; redraft asks what he will score
between now and the end of this season. Mixing them is how a win-now team
trades its season for a rookie pick, or a dynasty team sells a 22-year-old for
a rental.

`isDynasty(lg)` is true for `type` of `dynasty` or `keeper`. Everything that
reads a value goes through `val(p)`, which returns:

- **dynasty / keeper** → DynastyProcess value, superflex or 1QB per the lineup
- **redraft** → `rosValue(p)`

`rosValue` is rest-of-season points above replacement: the player's positional
rest-of-season consensus rank mapped through a points-per-rank curve **built in
this league's own scoring**, minus that league's replacement level, times his
remaining games with his bye removed. It is a real number with units, not an
index — and because replacement level depends on league size and lineup, the
same player prices differently in each league. Lamar Jackson, Week 3:

| League | Teams | ROS pts over replacement |
|---|---|---|
| ESPN 8-team | 8 | 59 |
| ESPN 10-team | 10 | 73.7 |
| ESPN 14-team | 14 | 85.3 |

That spread is the system working, not noise: a quarterback is worth more above
replacement in a 14-team league than an 8-team one.

The two bases live on different scales, so `valueScale()` (4000 dynasty, 90
redraft) normalises anything that folds a value into a 0–1 term, and
`valueLabel()` / `valueShort()` keep the UI honest about which is in use.

## What a redraft league no longer sees

- Dynasty value columns (`SF val`, `1QB val`, `Dyn SF`), replaced by `ROS pts`
  and `ROS/g`
- Rookie rank
- The rookie-pick reference table, and picks in trade search — replaced by a
  card explaining there is no next season to trade into
- The `U25 value` column in power rankings
- Age as a table column (it stays in the detail sheet as a plain fact; it is
  not a redraft valuation input)

Power rankings blend this week's ceiling with the active basis, weighted by
format, and say which. A saved sort key from another league's column set falls
back to `proj` rather than sorting by nothing.

## Kickers

The last position on a generic curve. Now stored as stat lines like everyone
else, keyed by Sleeper's scoring names:

```
fgm, fgm_0_19, fgm_20_29, fgm_30_39, fgm_40_49, fgm_50p, fgmiss, xpm, xpmiss
```

Projections come from Sleeper's distance buckets; season totals from nflverse
`fg_made_0_19 … fg_made_60_` plus PATs. nflverse scores kickers at zero, which
is fine — points are computed per league anyway.

The flat `fgm` key is kept **alongside** the buckets deliberately. Sleeper
treats buckets as full values with `fgm` additive (Tyler's league sets `fgm` to
0 and pays 3/3/3/4/6); other leagues pay a flat `fgm` with no buckets; others
pay flat plus a distance bonus. Storing both and letting the league multiply
handles all three with no special case.

Kickers and defenses also carry per-week stat lines in `wstats`, so their game
log is scored by the league rather than scaled from a PPR total.

Andy Borregales (NE) was missing from every id source. `add_kickers.py` now
creates a row for any feed kicker the database lacks — a starting kicker absent
from a league with a K slot is a hole, not a rounding error.

## Bug caught in testing

`DEFAULT_SCORING` had no kicker keys, so in the ESPN leagues every kicker with
a real stat line scored **zero**, and only kickers *without* one showed a number
via the fallback. Defaults now include 3/3/3/4/5 with −1 for a miss.

## Pipeline order

```
build_players.py → apply_sleeper_proj.py → add_poe.py
→ add_dst.py → add_pstats.py → add_kickers.py → build_leagues.py
→ build_standalone.py
```

`add_kickers.py` must run after `add_pstats.py`; it appends rows and would
otherwise have them overwritten.

## Verified

All four leagues × five tabs × the player sheet, plus a synthetic redraft clone
of the Sleeper roster to exercise the redraft trade and league paths that the
standings-only ESPN leagues can't reach. No console errors, no horizontal
overflow.
