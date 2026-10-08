#!/usr/bin/env python3
"""Overlay Sleeper's live Week 3 projections onto the model projections.

The relay that carries this data corrupts player ids (the same id comes back
for two different players), but names survive intact — so every line is matched
by NAME against the player database and the relayed id is thrown away. A line
whose name matches nothing is reported, never guessed at.
"""
import json, re, sys, unicodedata

OUT = "/home/claude/app/data"
WEEK = 3

def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    s = re.sub(r"[^a-z ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

# name|team|opp|pts — ids deliberately absent or ignored
FEEDS = {}
for pos, blob in [
 ("QB", """Lamar Jackson|BAL|DAL|24.49
Patrick Mahomes|KC|MIA|22.07
Josh Allen|BUF|LAC|21.91
Brock Purdy|SF|ARI|21.58
Trevor Lawrence|JAX|NE|20.79
Jared Goff|DET|NYJ|20.21
Jalen Hurts|PHI|CHI|19.74
Jaxson Dart|NYG|TEN|19.47
Drake Maye|NE|JAX|18.87
Joe Burrow|CIN|PIT|18.73
Kyler Murray|MIN|TB|18.45
Bo Nix|DEN|LAR|18.14
Malik Willis|MIA|KC|17.91
Bryce Young|CAR|CLE|17.67
Drew Lock|SEA|WAS|17.36
Justin Herbert|LAC|BUF|17.34
Dak Prescott|DAL|BAL|17.26
Jacoby Brissett|ARI|SF|16.33
Jordan Love|GB|ATL|16.17
Tyler Shough|NO|LV|16.12
Matthew Stafford|LAR|DEN|16.03
C.J. Stroud|HOU|IND|16.0
Baker Mayfield|TB|MIN|15.51
Kirk Cousins|LV|NO|15.18
Geno Smith|NYJ|DET|15.11
Cam Ward|TEN|NYG|14.45
Daniel Jones|IND|HOU|14.44
Aaron Rodgers|PIT|CIN|14.03
Marcus Mariota|WAS|SEA|13.86
Deshaun Watson|CLE|CAR|12.94
Tyson Bagent|CHI|PHI|12.16"""),
 ("RB", """Jahmyr Gibbs|DET|NYJ|23.4
Bijan Robinson|ATL|GB|20.43
Jonathan Taylor|IND|HOU|20.24
Christian McCaffrey|SF|ARI|19.92
Kenneth Walker|KC|MIA|19.52
Derrick Henry|BAL|DAL|19.26
De'Von Achane|MIA|KC|16.87
James Cook|BUF|LAC|16.21
Chase Brown|CIN|PIT|16.14
Saquon Barkley|PHI|CHI|16.1
Javonte Williams|DAL|BAL|15.5
Breece Hall|NYJ|DET|15.43
Omarion Hampton|LAC|BUF|15.19
Jeremiyah Love|ARI|SF|15.18
David Montgomery|HOU|IND|14.8
Cam Skattebo|NYG|TEN|14.75
Chuba Hubbard|CAR|CLE|14.49
Ashton Jeanty|LV|NO|14.34
Kyren Williams|LAR|DEN|13.71
TreVeyon Henderson|NE|JAX|13.45
Jaylen Warren|PIT|CIN|13.43
D'Andre Swift|CHI|PHI|13.13
Aaron Jones|MIN|TB|12.84
Bucky Irving|TB|MIN|12.76
Rico Dowdle|PIT|CIN|12.32
Quinshon Judkins|CLE|CAR|11.97
Bhayshul Tuten|JAX|NE|11.76
Tony Pollard|TEN|NYG|11.45
Jadarian Price|SEA|WAS|11.38
Rhamondre Stevenson|NE|JAX|11.02
Jacory Croskey-Merritt|WAS|SEA|10.64
Travis Etienne|NO|LV|10.2
MarShawn Lloyd|GB|ATL|9.74
Tyjae Spears|TEN|NYG|8.78
RJ Harvey|DEN|LAR|8.18
Blake Corum|LAR|DEN|8.18
Jonah Coleman|DEN|LAR|7.6
George Holani|SEA|WAS|7.45
Kenny Gainwell|TB|MIN|7.44
Tyler Allgeier|ARI|SF|7.43
Alvin Kamara|NO|LV|7.28
Keaton Mitchell|LAC|BUF|7.15
Kyle Monangai|CHI|PHI|6.91
Justice Hill|BAL|DAL|6.84
Woody Marks|HOU|IND|6.84
Chris Brooks|GB|ATL|6.64
Rachaad White|WAS|SEA|6.61
J.K. Dobbins|DEN|LAR|6.42
Braelon Allen|NYJ|DET|6.27
Chris Rodriguez|JAX|NE|5.89
Raheim Sanders|CLE|CAR|5.84
Kaelon Black|SF|ARI|5.18
Samaje Perine|CIN|PIT|5.18
Emmett Johnson|KC|MIA|4.63
Brian Robinson|ATL|GB|4.46
AJ Dillon|CAR|CLE|4.44
Kaleb Johnson|GB|ATL|4.3
DeeJay Dallas|MIN|TB|3.87
Emari Demercado|DAL|BAL|3.82
Najee Harris|NYG|TEN|3.82
Mike Washington|LV|NO|3.19
Ray Davis|BUF|LAC|2.98
Will Shipley|PHI|CHI|2.64
Demond Claiborne|MIN|TB|2.54
Isaiah Davis|NYJ|DET|2.44
Ty Johnson|BUF|LAC|2.41
Ollie Gordon|MIA|KC|2.13
Sione Vaki|DET|NYJ|2.12
Tyler Badie|DEN|LAR|2.0"""),
 ("WR", """Jaxon Smith-Njigba|SEA|WAS|22.56
Amon-Ra St. Brown|DET|NYJ|19.88
Ja'Marr Chase|CIN|PIT|18.1
Puka Nacua|LAR|DEN|17.1
Justin Jefferson|MIN|TB|16.9
Chris Olave|NO|LV|16.74
Zay Flowers|BAL|DAL|16.58
CeeDee Lamb|DAL|BAL|16.41
DeVonta Smith|PHI|CHI|16.4
Parker Washington|JAX|NE|15.59
Christian Watson|GB|ATL|15.22
Jalen Coker|CAR|CLE|15.08
Nico Collins|HOU|IND|14.93
Garrett Wilson|NYJ|DET|14.85
Tee Higgins|CIN|PIT|14.64
Malik Nabers|NYG|TEN|14.5
Tetairoa McMillan|CAR|CLE|14.45
George Pickens|DAL|BAL|14.23
Jaylen Waddle|DEN|LAR|13.92
Ladd McConkey|LAC|BUF|13.87
Mike Evans|SF|ARI|13.63
Drake London|ATL|GB|13.48
Jameson Williams|DET|NYJ|12.81
Rashee Rice|KC|MIA|12.58
Michael Wilson|ARI|SF|12.28
DJ Moore|BUF|LAC|11.53
Deebo Samuel|SF|ARI|11.46
Josh Downs|IND|HOU|11.17
Matthew Golden|GB|ATL|11.03
DK Metcalf|PIT|CIN|11.0
Courtland Sutton|DEN|LAR|10.74
Xavier Worthy|KC|MIA|10.67
Luther Burden|CHI|PHI|10.62
Davante Adams|LAR|DEN|10.58
Terry McLaurin|WAS|SEA|10.42
Khalil Shakir|BUF|LAC|10.22
Rashod Bateman|BAL|DAL|10.09
Carnell Tate|TEN|NYG|10.0
Emeka Egbuka|TB|MIN|9.93
Chris Godwin|TB|MIN|9.84
Stefon Diggs|WAS|SEA|9.81
Malik Washington|MIA|KC|9.79
Dontayvion Wicks|PHI|CHI|9.7
Denzel Boston|CLE|CAR|9.62
Devaughn Vele|NO|LV|9.55
Wan'Dale Robinson|TEN|NYG|9.43
Jordan Addison|MIN|TB|9.3
Brian Thomas|JAX|NE|9.22
Michael Pittman|PIT|CIN|9.17
KC Concepcion|CLE|CAR|9.15
Adonai Mitchell|NYJ|DET|9.14
Rome Odunze|CHI|PHI|9.11
Romeo Doubs|NE|JAX|8.96
Quentin Johnston|LAC|BUF|8.93
Tre Tucker|LV|NO|8.89
Rashid Shaheed|SEA|WAS|8.65
Jakobi Meyers|JAX|NE|8.52
Mack Hollins|NE|JAX|8.11
Pat Bryant|DEN|LAR|7.77
Kayshon Boutte|HOU|IND|7.56
Keenan Allen|IND|HOU|7.51
DeMario Douglas|NE|JAX|7.43
Ryan Flournoy|DAL|BAL|7.43
Makai Lemon|PHI|CHI|7.69
Caleb Douglas|MIA|KC|7.24
Tre' Harris|LAC|BUF|7.16
Tyquan Thornton|KC|MIA|7.08
Jauan Jennings|MIN|TB|7.04
Marvin Harrison|ARI|SF|7.0
Keon Coleman|BUF|LAC|7.0
Kalif Raymond|CHI|PHI|6.93
Cooper Kupp|SEA|WAS|6.81
Jalen Nailor|LV|NO|6.69
Jerry Jeudy|SF|ARI|6.69"""),
 ("TE", """Trey McBride|ARI|SF|17.33
Brock Bowers|LV|NO|13.68
Travis Kelce|KC|MIA|13.22
Dalton Kincaid|BUF|LAC|12.71
Sam LaPorta|DET|NYJ|12.43
George Kittle|SF|ARI|12.39
Mark Andrews|BAL|DAL|11.65
Tucker Kraft|GB|ATL|11.61
Dalton Schultz|HOU|IND|10.56
Hunter Henry|NE|JAX|10.54
Isaiah Likely|NYG|TEN|10.46
Colston Loveland|CHI|PHI|10.43
Tyler Warren|IND|HOU|10.28
Juwan Johnson|NO|LV|9.93
Brenton Strange|JAX|NE|9.47
Kyle Pitts|ATL|GB|9.47
Jake Ferguson|DAL|BAL|9.16
Harold Fannin|CLE|CAR|9.0
T.J. Hockenson|MIN|TB|8.92
Oronde Gadsden|LAC|BUF|8.85
AJ Barner|SEA|WAS|8.63
Pat Freiermuth|PIT|CIN|8.4
Darren Waller|CAR|CLE|8.27
Gunnar Helm|TEN|NYG|7.31
Cade Otton|TB|MIN|7.16
Mike Gesicki|CIN|PIT|6.69
Greg Dulcich|MIA|KC|5.93
Chig Okonkwo|WAS|SEA|5.61
Evan Engram|DEN|LAR|5.5
Noah Gray|KC|MIA|5.19
Kenyon Sadiq|NYJ|DET|5.05
Colby Parkinson|LAR|DEN|5.0
Michael Mayer|LV|NO|4.52
Dawson Knox|BUF|LAC|4.06
Jonnu Smith|GB|ATL|3.88
Cole Kmet|CHI|PHI|3.78
Theo Johnson|NYG|TEN|3.61
Terrance Ferguson|LAR|DEN|3.59
Darnell Washington|PIT|CIN|3.5
Mason Taylor|NYJ|DET|3.4
Ben Sinnott|WAS|SEA|3.21
Elijah Arroyo|SEA|WAS|3.2
Noah Fant|NO|LV|3.15
Will Kacmarek|MIA|KC|3.09
Tommy Tremble|CAR|CLE|3.04
Erick All|CIN|PIT|2.93
Marlin Klein|HOU|IND|2.92
Brock Wright|DET|NYJ|2.87
Josh Oliver|MIN|TB|2.61
Luke Farrell|SF|ARI|2.58
Durham Smythe|BAL|DAL|2.57
Johnny Mundt|PHI|CHI|2.56
Oscar Delp|NO|LV|2.46
Austin Hooper|ATL|GB|2.35
Daniel Bellinger|TEN|NYG|2.25
Drew Sample|CIN|PIT|2.1
Matt Hibner|BAL|DAL|2.03
Adam Trautman|DEN|LAR|1.85
Eli Raridon|NE|JAX|1.85
Elijah Higgins|ARI|SF|1.84
Cade Stover|HOU|IND|1.68
John Bates|WAS|SEA|1.64
Blake Whiteheart|CLE|CAR|1.63
Tyler Higbee|LAR|DEN|1.62
Sam Roush|CHI|PHI|1.6
E.J. Jenkins|PHI|CHI|1.6
Luke Schoonmaker|DAL|BAL|1.52
Nate Boerkircher|JAX|NE|1.52
Tanner Koziol|JAX|NE|1.3
Foster Moreau|HOU|IND|1.28
Brevyn Spann-Ford|DAL|BAL|1.18
Jackson Hawes|BUF|LAC|1.16
Mo Alie-Cox|IND|HOU|1.12
Josh Cuevas|BAL|DAL|1.0
Mitchell Evans|CAR|CLE|0.99
Max Klare|LAR|DEN|0.96
Jeremy Ruckert|NYJ|DET|0.91
Seydou Traore|MIA|KC|0.87
Charlie Woerner|ATL|GB|0.71"""),
]:
    for line in blob.strip().splitlines():
        name, team, opp, pts = line.split("|")
        FEEDS.setdefault(pos, {})[norm(name)] = (team, opp, float(pts))

players = json.load(open(f"{OUT}/players.json"))
by_pos_key = {}
for p in players:
    by_pos_key.setdefault(p["pos"], {})[p["key"]] = p

matched, unmatched, conflicts = 0, [], []
for pos, feed in FEEDS.items():
    for key, (team, opp, pts) in feed.items():
        p = by_pos_key.get(pos, {}).get(key)
        if not p:
            unmatched.append(f"{pos} {key}")
            continue
        if p["team"] not in ("FA", team):
            conflicts.append(f"{p['name']}: db has {p['team']}, Sleeper says {team}")
        p["proj_model"] = p.get("proj")
        p["proj"] = round(pts, 2)
        p["proj_src"] = "sleeper"
        p["opp"] = opp
        p["team"] = team
        matched += 1

# Everyone Sleeper didn't cover keeps the model number — but a week-old injury
# report is now only a flag, never a multiplier that benches a healthy starter.
SOFT = {"Out": 0.55, "Doubtful": 0.70, "Questionable": 0.95}
rebuilt = 0
for p in players:
    if p.get("proj_src") == "sleeper":
        continue
    parts = p.get("proj_parts")
    if not parts:
        p["proj_src"] = "model"
        continue
    hard = parts.get("avail", 1.0)
    if hard in (0.15, 0.45, 0.92) and p.get("proj") is not None:
        soft = SOFT.get(p.get("inj"), 1.0)
        p["proj"] = round(p["proj"] / hard * soft, 2)
        parts["avail"] = soft
        rebuilt += 1
    p["proj_src"] = "model"

# points above replacement follows the new projections
meta = json.load(open(f"{OUT}/meta.json"))
repl = meta.get("replacement", {})
for p in players:
    r = repl.get(p["pos"])
    p["par"] = round(p["proj"] - r, 2) if (r is not None and p.get("proj") is not None) else None

meta["proj_source"] = "sleeper-live + model fallback"
meta["proj_week"] = WEEK
meta["proj_counts"] = {"sleeper": matched,
                       "model": sum(1 for p in players if p.get("proj_src") == "model")}
json.dump(players, open(f"{OUT}/players.json", "w"), separators=(",", ":"), allow_nan=False)
json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=1, allow_nan=False)

print(f"matched by name: {matched}   un-benched by softening stale injuries: {rebuilt}")
print(f"unmatched feed names ({len(unmatched)}): {unmatched[:12]}")
print(f"team conflicts ({len(conflicts)}): {conflicts[:8]}")
