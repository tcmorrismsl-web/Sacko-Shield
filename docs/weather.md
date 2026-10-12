# Weather adjustments

The refresh job (`pipeline/overlay/refresh.py`) pulls an hourly forecast from
Open-Meteo for every game still to be played that week, averaged over the hours
the game overlaps (kickoff to kickoff + 190 min). Outdoor games get stat
multipliers; fixed domes get nothing; retractable roofs (ATL, DAL, HOU, IND,
ARI, Madrid) show the forecast in the tooltip but are not adjusted, because the
roof is usually closed in exactly the weather that would matter.

## Where the numbers come from

Measured, not borrowed: nflverse `games.csv` (observed kickoff `wind` and
`temp`) joined to `stats_team_week` for 2016–2025 regular seasons. Each
team-game's output is divided by the same team's season average with that game
left out, so team quality drops out. Wind effects are measured in games above
40°F; cold effects in games under 10 mph, so the two are not double-counted.

| Wind (warm games) | n | pass yds | pass TD | completions | FG att |
|---|---|---|---|---|---|
| 0–9 mph | 1887 | 1.000 | 1.000 | 1.000 | 1.000 |
| 10–14 | 584 | 0.958 | 0.918 | 0.973 | 0.996 |
| 15–19 | 239 | 0.925 | 0.916 | 0.959 | 0.960 |
| 20+ | 50 | 0.874 | 0.956 | 0.878 | 1.040* |

| Temperature (calm games) | n | pass yds | pass TD | completions | FG att |
|---|---|---|---|---|---|
| > 40°F | 1887 | 1.000 | 1.000 | 1.000 | 1.000 |
| 26–40 | 286 | 0.950 | 1.031 | 0.954 | 0.902 |
| ≤ 25 | 51 | 0.934 | 0.679* | 0.917 | 0.826 |

\* small samples. For 20+ mph field goals the all-temperature figure (0.89,
n=81 games) is used; for ≤25°F touchdowns the yardage factor is used rather than
0.68. Standard error on the passing-yards ratio is about 0.02 at 15–19 mph and
0.04 at 20+.

FG **accuracy** barely moves with wind (teams attempt fewer and shorter kicks),
so wind and cold scale field-goal attempts — makes and misses together — not
the make rate. Rushing showed no consistent effect and is never adjusted.

## Multipliers applied

| | yards | TDs | receptions | field goals |
|---|---|---|---|---|
| wind 10–14 mph | 0.96 | 0.92 | 0.97 | 1.00 |
| wind 15–19 | 0.92 | 0.92 | 0.96 | 0.96 |
| wind 20+ | 0.87 | 0.91 | 0.88 | 0.90 |
| 26–40°F | 0.95 | 1.00 | 0.95 | 0.90 |
| ≤ 25°F | 0.93 | 0.93 | 0.92 | 0.83 |

Wind and cold multiply together. "Yards" covers passing and receiving yards and
first downs; "TDs" passing and receiving TDs; "receptions" receptions,
completions and per-reception bonuses; "field goals" every fgm/fgmiss/fga key.

## Precipitation

games.csv has no rain or snow history, so there is nothing to measure an effect
from. Rain (≥50% chance and ≥0.1 in over the game window) and snow (≥0.2 in) are
**flagged only**, never applied to the numbers.

## Caveats

- The effects were measured on observed game-time weather and are applied to
  forecasts; forecast error makes the real effect a little smaller.
- Whether Sleeper's own projections already price weather is not documented.
  If they do, this partially double-counts. The adjustment is shown on every
  affected player (weather chip tooltip) so it is never hidden.
