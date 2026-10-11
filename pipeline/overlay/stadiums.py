"""Stadium locations and roof types, keyed by nflverse games.csv `stadium_id`.

nflverse's own `roof` column is not usable for this: retractable roofs are
blank for most games, and several open-air international venues (Stade de
France, the MCG, Munich's Allianz Arena) are listed as "dome". Roof here is:

  outdoor      weather applies
  dome         fixed roof, no weather
  retractable  open/closed is decided on game day, so the forecast is shown
               but no adjustment is made

Coordinates are the stadium itself (to ~0.5 km), which is finer than the
weather model's grid, so they are exact enough for a forecast.
An unknown stadium_id gets no weather rather than a guessed location.
"""

STADIUMS = {
    "ATL97": ("Mercedes-Benz Stadium", 33.7554, -84.4008, "retractable"),
    "BAL00": ("M&T Bank Stadium", 39.2780, -76.6227, "outdoor"),
    "BOS00": ("Gillette Stadium", 42.0909, -71.2643, "outdoor"),
    "BUF00": ("Highmark Stadium", 42.7738, -78.7870, "outdoor"),
    "CAR00": ("Bank of America Stadium", 35.2258, -80.8528, "outdoor"),
    "CHI98": ("Soldier Field", 41.8623, -87.6167, "outdoor"),
    "CIN00": ("Paycor Stadium", 39.0955, -84.5161, "outdoor"),
    "CLE00": ("Huntington Bank Field", 41.5061, -81.6995, "outdoor"),
    "DAL00": ("AT&T Stadium", 32.7473, -97.0945, "retractable"),
    "DEN00": ("Empower Field at Mile High", 39.7439, -105.0201, "outdoor"),
    "DET00": ("Ford Field", 42.3400, -83.0456, "dome"),
    "GNB00": ("Lambeau Field", 44.5013, -88.0622, "outdoor"),
    "HOU00": ("NRG Stadium", 29.6847, -95.4107, "retractable"),
    "IND00": ("Lucas Oil Stadium", 39.7601, -86.1639, "retractable"),
    "JAX00": ("EverBank Stadium", 30.3239, -81.6373, "outdoor"),
    "KAN00": ("GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "outdoor"),
    "LAX01": ("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "MIA00": ("Hard Rock Stadium", 25.9580, -80.2389, "outdoor"),
    "MIN01": ("U.S. Bank Stadium", 44.9737, -93.2581, "dome"),
    "NAS00": ("Nissan Stadium", 36.1665, -86.7713, "outdoor"),
    "NOR00": ("Caesars Superdome", 29.9511, -90.0812, "dome"),
    "NYC01": ("MetLife Stadium", 40.8135, -74.0745, "outdoor"),
    "PHI00": ("Lincoln Financial Field", 39.9008, -75.1675, "outdoor"),
    "PHO00": ("State Farm Stadium", 33.5276, -112.2626, "retractable"),
    "PIT00": ("Acrisure Stadium", 40.4468, -80.0158, "outdoor"),
    "SEA00": ("Lumen Field", 47.5952, -122.3316, "outdoor"),
    "SFO01": ("Levi's Stadium", 37.4030, -121.9700, "outdoor"),
    "TAM00": ("Raymond James Stadium", 27.9759, -82.5033, "outdoor"),
    "VEG00": ("Allegiant Stadium", 36.0909, -115.1833, "dome"),
    "WAS00": ("Northwest Stadium", 38.9076, -76.8645, "outdoor"),
    # international and neutral sites
    "LON00": ("Wembley Stadium", 51.5560, -0.2796, "outdoor"),
    "LON02": ("Tottenham Hotspur Stadium", 51.6043, -0.0664, "outdoor"),
    "MAD01": ("Santiago Bernabeu", 40.4531, -3.6883, "retractable"),
    "MEL00": ("Melbourne Cricket Ground", -37.8200, 144.9834, "outdoor"),
    "MEX00": ("Estadio Banorte", 19.3029, -99.1505, "outdoor"),
    "MUN01": ("Allianz Arena", 48.2188, 11.6247, "outdoor"),
    "PAR00": ("Stade de France", 48.9245, 2.3602, "outdoor"),
    "RIO00": ("Maracana Stadium", -22.9122, -43.2302, "outdoor"),
}
