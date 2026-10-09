#!/usr/bin/env python3
"""Turn the Artifact page into one self-contained HTML file.

Three things change when the app leaves claude.ai:
  * the page must carry its own <!doctype>, head and reset — the Artifact
    platform supplies those at publish time;
  * the data files can't be fetched as siblings, so they are inlined;
  * window.claude capabilities don't exist, so downloads fall back to a Blob
    and saved state falls back to localStorage.

And one thing gets better: no artifact CSP, so the page can call the Sleeper
API directly from the browser and refresh itself.
"""
import argparse, json, pathlib, re

ap = argparse.ArgumentParser()
ap.add_argument("--app", default="/home/claude/app", help="folder holding index.html and data/")
ap.add_argument("--out", default="/mnt/user-data/outputs/sacko-shield.html")
ap.add_argument("--public", action="store_true",
                help="build for GitHub Pages: ship NO league data (no manager or team "
                     "names, no league IDs); viewers connect their own leagues in the browser")
args = ap.parse_args()

APP = pathlib.Path(args.app)
OUT = pathlib.Path(args.out)
DATA = ["players", "schedule", "picks", "meta", "leagues"]

# A single placeholder league for the public build. The app needs at least one
# league to boot; this one has generic team names and no IDs. Leagues the viewer
# connects are saved in their own browser (localStorage), never in this file.
PLACEHOLDER = [{
    "key": "placeholder", "sample": True, "source": "placeholder", "platform": "Demo",
    "name": "Connect your league", "league_id": None, "season": 2026, "type": "redraft",
    "teams": 10, "scoring": "ppr",
    "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K"] + ["BN"] * 6,
    "my_team": "1", "status": "standings_only",
    "note": "No league data ships with this public copy. Use Connect to load your "
            "Sleeper or ESPN league; it is saved in this browser only.",
    "rosters": [{"id": str(i), "name": f"Team {i}", "owner": "", "players": [],
                 "starters": [], "picks": [], "wins": 0, "losses": 0,
                 "pf": 0.0, "pa": 0.0} for i in range(1, 11)],
    "results": [],
}]

src = (APP / "index.html").read_text()

# ---------------------------------------------------------------- data inline
blobs = []
for name in DATA:
    if args.public and name == "leagues":
        raw = json.dumps(PLACEHOLDER, separators=(",", ":"))
    elif args.public and name == "meta":
        meta = json.loads((APP / "data" / "meta.json").read_text())
        for k in ("league_verification", "build_note"):   # league-specific notes
            meta.pop(k, None)
        raw = json.dumps(meta, separators=(",", ":"))
    else:
        raw = (APP / "data" / f"{name}.json").read_text()
    # a JSON string containing "</script>" would close the tag early
    safe = raw.replace("</", "<\\/")
    blobs.append('<script type="application/json" id="d-%s">%s</script>'
                 % (name, safe))
DATA_BLOCK = "\n".join(blobs)

def swap(old, new, why):
    global src
    if old not in src:
        raise SystemExit(f"anchor missing — {why}:\n{old[:120]}")
    src = src.replace(old, new, 1)

# 1. loading ------------------------------------------------------------------
swap('''async function loadJSON(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}''',
'''const STANDALONE = true;

/** Data ships inside this file rather than as sibling downloads. */
async function loadJSON(path) {
  const name = path.replace(/^data\\//, "").replace(/\\.json$/, "");
  const el = document.getElementById("d-" + name);
  if (!el) throw new Error("missing embedded data: " + name);
  return JSON.parse(el.textContent);
}

/** Hand the viewer a file. No capability here — just a Blob and a click. */
function saveFile(filename, data) {
  const blob = data instanceof Blob ? data
    : new Blob([data], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.style.display = "none";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return Promise.resolve({ status: "saved" });
}''', "loadJSON")

# 2. export -------------------------------------------------------------------
swap('''  if (!DOWNLOADS) { toast("Downloads aren't available in this view."); return; }
  try {
    await DOWNLOADS.save({ filename: name, data: buf });
    toast("Saved " + name);
  } catch (e) {
    toast(e?.code === "declined" ? "Export cancelled" : "Couldn't save that file.");
  }''',
'''  try {
    await saveFile(name, buf);
    toast("Saved " + name);
  } catch {
    toast("Couldn't save that file.");
  }''', "export")

# 3. state --------------------------------------------------------------------
swap('''async function saveState(extra = {}) {
  if (!DB || !USER_ID) return;
  try {
    await DB.doc(`data/users/${USER_ID}/prefs`).set({
      myTeam: S.myTeam, tab: S.tab, ...extra, savedAt: new Date().toISOString(),
    });
  } catch {}
}

async function loadState() {
  if (!DB || !USER_ID) return null;
  try {
    const snap = await DB.doc(`data/users/${USER_ID}/prefs`).get();
    return snap.exists ? snap.data() : null;
  } catch { return null; }
}

/* Leagues the viewer connected themselves. On claude.ai they last for the
   session; the standalone build swaps these for localStorage. */
function saveConnected(lg) {
  try {
    if (!DB || !USER_ID) return;
    DB.doc(`data/users/${USER_ID}/league_${lg.key}`).set({
      key: lg.key, source: lg.source, league_id: lg.league_id,
      my_team: lg.my_team, savedAt: new Date().toISOString(),
    });
  } catch {}
}
function loadConnected() { return []; }''',
'''const PREFS = "sacko.prefs";

async function saveState(extra = {}) {
  try {
    const prev = JSON.parse(localStorage.getItem(PREFS) || "{}");
    localStorage.setItem(PREFS, JSON.stringify({
      ...prev, myTeam: S.myTeam, tab: S.tab, ...extra,
      savedAt: new Date().toISOString(),
    }));
  } catch {}
}

async function loadState() {
  try { return JSON.parse(localStorage.getItem(PREFS) || "null"); }
  catch { return null; }
}

/** Leagues the viewer connected themselves, kept between visits. */
function saveConnected(lg) {
  try {
    const all = JSON.parse(localStorage.getItem("sacko.leagues") || "[]");
    localStorage.setItem("sacko.leagues", JSON.stringify(
      [...all.filter(l => l.key !== lg.key),
       Object.assign({}, lg, { _savedAt: new Date().toISOString() })]));
  } catch {}
}

/**
 * A league stored here outranks the one shipped in this file only when it is
 * newer than the build. Without that rule a single ESPN load is pinned in
 * browser storage forever: every later rebuild of this file is read, then
 * thrown away, and the viewer sees stale rosters with no way to tell why.
 */
function loadConnected() {
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem("sacko.leagues") || "[]"); }
  catch { return []; }
  const built = S.meta && S.meta.built ? Date.parse(S.meta.built) : NaN;
  const shipped = new Set((S.leagues || []).filter(hasRosters).map(l => l.key));
  return saved.filter(l => {
    if (!shipped.has(l.key)) return true;         // nothing shipped to protect
    const at = l._savedAt ? Date.parse(l._savedAt) : NaN;
    return !(built > 0) || (at > 0 && at > built);
  });
}''', "state")

# 4. capabilities are gone; keep the boot block but make it a no-op ------------
swap('''  (async () => {
    const use = async name => {
      try { return (await window.claude?.use?.(name)) ?? null; } catch { return null; }
    };
    [DOWNLOADS, DB] = await Promise.all(["downloads", "db"].map(use));
    const u = await use("user");
    if (u) { try { USER_ID = await u.id(); } catch { USER_ID = null; } }
    // The store is also the live-score relay — subscribe as soon as it resolves.
    subscribeRelay();
    applyManual(await loadManual());
    const saved = await loadState();''',
'''  (async () => {
    const saved = await loadState();''', "capabilities")

# 5. connect flow: live Sleeper genuinely works off-platform -------------------
swap('''    } catch {
      msg.innerHTML = `This page can't reach Sleeper directly — claude.ai blocks published
        pages from calling outside APIs. Send the league ID to Claude in the chat and it will
        load your league into this app.`;
    }''',
'''    } catch (err) {
      msg.innerHTML = `Couldn't load that league — check the ID, or Sleeper may be
        briefly unavailable. <span class="sub">(${esc(String(err?.message || err))})</span>`;
    }''', "connect message")

swap('''      S.leagues = [...S.leagues.filter(l => l.key !== lgNew.key), lgNew];
      S.live = true;''',
'''      S.leagues = [...S.leagues.filter(l => l.key !== lgNew.key), lgNew];
      S.live = true;
      saveConnected(lgNew);
      dropPlaceholder();''', "persist connected league")

swap('''      <span class="eyebrow">Add another Sleeper league</span>
      <input type="text" id="lidInput" placeholder="Sleeper league ID"
        aria-label="Sleeper league ID">
      <div class="row"><button class="btn" id="lidGo">Load league</button></div>''',
'''      <span class="eyebrow">Add or refresh a Sleeper league</span>
      <input type="text" id="lidInput" placeholder="Sleeper league ID"
        value="${esc(lg.source === "sleeper" ? (lg.league_id || "") : "")}"
        aria-label="Sleeper league ID">
      <div class="row"><button class="btn" id="lidGo">Load from Sleeper</button>
        <span class="sub">This copy talks to Sleeper directly — rosters,
          records and starters come back live.</span></div>''', "connect copy")

# 6. boot: restore connected leagues, then refresh the Sleeper one quietly -----
swap('''  S.league = leagues.find(hasRosters) || leagues[0];''',
'''  const extra = loadConnected();
  if (extra.length)
    S.leagues = [...leagues.filter(l => !extra.some(e => e.key === l.key)), ...extra];
  // leagues restored from localStorage haven't been through the capture above
  for (const lg of S.leagues)
    if (!lg._shipped) lg._shipped = Object.fromEntries(
      lg.rosters.map(r => [r.id, (r.players || []).slice()]));
  dropPlaceholder();
  S.league = S.leagues.find(hasRosters) || S.leagues[0];''', "boot leagues")

swap('''    const saved = await loadState();
    if (saved?.leagueKey && S.leagues.some(l => l.key === saved.leagueKey)) {''',
'''    const fromLink = await loadFromLink();
    refreshSleeper();
    const saved = await loadState();
    if (saved?.leagueKey && S.leagues.some(l => l.key === saved.leagueKey)) {''',
     "boot refresh")

# 7. personal link: leagues + your team in the URL, so any device loads them ----
swap('''function openConnect() {''',
'''/* ------------------------------------------------------------ personal link
   The public copy ships no league data. A personal link carries league IDs and
   which team is yours in the URL fragment (after #), which browsers never send
   to the server:  #leagues=s:<sleeperId>:<rosterId>,e:<espnId>:<teamId>
   Opening it on any device loads those leagues live and saves them in that
   browser, so a bookmark or home-screen icon "locks in" the leagues. */
function dropPlaceholder() {
  if (S.leagues.some(l => l.source !== "placeholder"))
    S.leagues = S.leagues.filter(l => l.source !== "placeholder");
}

function parseLink() {
  const m = /(?:^|[#&])leagues=([^&]+)/.exec(location.hash);
  if (!m) return [];
  return decodeURIComponent(m[1]).split(",").map(part => {
    const [src, id, team] = part.split(":");
    if (!/^[se]$/.test(src) || !/^\\d{3,25}$/.test(id || "")) return null;
    return { src, id, team: team || "", key: (src === "s" ? "sleeper-" : "espn-") + id };
  }).filter(Boolean);
}

function myLink() {
  const parts = S.leagues.filter(l => l.league_id && l.source !== "placeholder").map(l => {
    const team = l.key === S.league.key ? S.myTeam : l.my_team;
    return `${l.source === "espn" ? "e" : "s"}:${l.league_id}${team ? ":" + team : ""}`;
  });
  return parts.length ? `${location.origin}${location.pathname}#leagues=${parts.join(",")}` : "";
}

async function loadFromLink() {
  const want = parseLink();
  if (!want.length) return null;
  const failed = [];
  for (const w of want) {
    let lg = S.leagues.find(l => l.key === w.key);
    if (!lg || !hasRosters(lg)) {
      try {
        let fresh = w.src === "s" ? await trySleeper(w.id)
                                  : await tryEspn(w.id, S.meta.season);
        fresh.key = w.key;
        if (w.src === "s") { fresh.status = "full"; fresh.platform = "Sleeper"; }
        lg = mergeLeague(lg, fresh);
      } catch (err) { failed.push(w.id); continue; }
    }
    // the link sets your team once; a team you pick later in the app wins
    if (w.team && !lg._teamPicked && lg.rosters.some(r => r.id === w.team)) {
      lg.my_team = w.team; lg._teamPicked = true;
    }
    if (!lg.my_team && lg.rosters.length) lg.my_team = lg.rosters[0].id;
    for (const r of lg.rosters)
      if (!(lg._shipped || {})[r.id]) (lg._shipped = lg._shipped || {})[r.id] = (r.players || []).slice();
    S.leagues = [...S.leagues.filter(l => l.key !== lg.key), lg];
    saveConnected(lg);
  }
  dropPlaceholder();
  const first = want.map(w => w.key).find(k => S.leagues.some(l => l.key === k));
  if (first) switchLeague(first);
  if (failed.length) toast(`Couldn't load league ${failed.join(", ")} — tap League to retry.`);
  return first || null;
}

function openConnect() {''', "personal link helpers")

# the team you pick is remembered per league, not one number for every league
swap('''  $("#teamSel", el)?.addEventListener("change", e => {
    S.myTeam = e.target.value; saveState(); show(S.tab);
  });''',
'''  $("#teamSel", el)?.addEventListener("change", e => {
    S.myTeam = e.target.value; S.league.my_team = S.myTeam; S.league._teamPicked = true;
    if (S.league.source !== "placeholder") saveConnected(S.league);
    saveState(); show(S.tab);
  });
  $("#linkCopy", el)?.addEventListener("click", async () => {
    const url = myLink(), box = $("#linkBox", el);
    if (!url) { box.value = "Connect a league first."; return; }
    box.value = url; box.hidden = false; box.select();
    try { await navigator.clipboard.writeText(url); $("#linkCopy", el).textContent = "Copied"; }
    catch { $("#linkCopy", el).textContent = "Select and copy below"; }
  });''', "team per league + copy link")

swap('''    <hr class="divider">
    <div class="stack" style="gap:7px">
      <span class="eyebrow">Export</span>''',
'''    <hr class="divider">
    <div class="stack" style="gap:7px">
      <span class="eyebrow">Your personal link</span>
      <div class="row"><button class="btn" id="linkCopy">Copy my link</button></div>
      <input type="text" id="linkBox" readonly hidden aria-label="Your personal link">
      <span class="sub">Bookmark it or add it to your home screen. Opening it on any
        device loads these leagues and your team automatically — no reconnecting.
        Pick your team in each league first.</span>
    </div>

    <hr class="divider">
    <div class="stack" style="gap:7px">
      <span class="eyebrow">Export</span>''', "personal link section")

# a team picked for this league beats the one global number from last visit
swap('''    if (saved?.myTeam && S.league.rosters.some(r => r.id === saved.myTeam)) {''',
'''    if (S.league.my_team && S.league.source !== "placeholder") {
      S.myTeam = S.league.my_team; show(S.tab);
    } else if (saved?.myTeam && S.league.rosters.some(r => r.id === saved.myTeam)) {''',
     "per-league team on boot")

# a refresh must not forget that you chose your team in this league
swap('''  for (const k of ["scoring_settings", "scoring_partial", "note", "platform",
                   "type", "season"]) {''',
'''  for (const k of ["scoring_settings", "scoring_partial", "note", "platform",
                   "type", "season", "_teamPicked"]) {''', "keep team pick on refresh")

swap('''/* -------------------------------------------------------------------- boot */''',
'''/** Quietly pull fresh rosters for every league we already know about. */
async function refreshSleeper() {
  const targets = S.leagues.filter(l => l.league_id);
  for (const old of targets) {
    try {
      let fresh = old.source === "espn"
        ? await tryEspn(old.league_id, old.season || S.meta.season)
        : await trySleeper(old.league_id);
      fresh.key = old.key;
      fresh.platform = old.platform;
      // never let a refresh drop what the fetch can't supply
      fresh = mergeLeague(old, fresh);
      if (old.source !== "espn") fresh.status = "full";
      if (!hasRosters(fresh) && hasRosters(old)) continue;   // never downgrade
      // keep the team the viewer picked, matched by name across the refresh
      const mine = old.rosters.find(r => r.id === old.my_team);
      fresh.my_team = (fresh.rosters.find(r => r.name === mine?.name)
        || fresh.rosters.find(r => r.id === old.my_team) || fresh.rosters[0]).id;
      S.leagues = S.leagues.map(l => l.key === old.key ? fresh : l);
      if (S.league.key === old.key) {
        S.league = fresh;
        if (!fresh.rosters.some(r => r.id === S.myTeam)) S.myTeam = fresh.my_team;
        S.live = true;
        show(S.tab);
        toast("Refreshed " + fresh.name + " from " + fresh.platform);
      }
    } catch { /* offline or rate-limited — the shipped snapshot still works */ }
  }
}

/* -------------------------------------------------------------------- boot */''',
     "refreshSleeper")

# 6b. live scoring now lives in the shared source and runs in both builds, so
#     there is nothing to inject here. Whether a published page may call an
#     outside API is a sandbox property this session cannot test; the app tries
#     and reports what happened instead of assuming.

# 7. provenance line should not claim a snapshot when it refreshed ------------
swap('''    <div class="srcline">League: <b>${esc(S.league.platform)} · ${esc(S.league.name)}</b>${
      hasRosters(S.league) ? " — rosters verified against the player database"
        : " — standings only"}.</div>''',
'''    <div class="srcline">League: <b>${esc(S.league.platform)} · ${esc(S.league.name)}</b>${
      S.live ? " — pulled live from Sleeper just now"
        : hasRosters(S.league) ? " — snapshot taken when this file was built"
        : " — standings only"}.</div>
    <div class="srcline">This is the standalone build: player data is baked in and
      refreshes when you rebuild the file; Sleeper leagues refresh themselves every
      time you open the page.</div>''', "provenance")

# ------------------------------------------------------------------- assemble
doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="Dynasty and redraft fantasy football cockpit — start/sit, waivers, trade values, league analysis and Excel export.">
<meta name="color-scheme" content="light dark">
<style>
  :root {{
    color-scheme: light dark;
    padding-top: env(safe-area-inset-top, 0px);
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }}
  body {{ margin: 0; font: 14px system-ui, sans-serif; }}
  img {{ max-width: 100%; }}
  [hidden] {{ display: none !important; }}
</style>
{DATA_BLOCK}
{src}
</head>
</html>
"""
# the page's own <title>/<style>/markup live in `src`; move everything that is
# not head-legal into the body
doc = doc.replace("</head>\n</html>", "</head>\n<body></body>\n</html>")
head_end = doc.index("<style>\n:root{")
title_block, rest = doc[:head_end], doc[head_end:]
doc = title_block + "</head>\n<body>\n" + rest.replace(
    "</head>\n<body></body>\n</html>", "</body>\n</html>")

# Guard: a public build must not contain any name or ID from the local leagues file.
if args.public and (APP / "data" / "leagues.json").exists():
    leaked = set()
    for lg in json.loads((APP / "data" / "leagues.json").read_text()):
        terms = {lg.get("name"), str(lg.get("league_id") or "")}
        for r in lg.get("rosters", []):
            terms |= {r.get("name"), r.get("owner")}
        for t in terms:
            if t and len(t) >= 4 and re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", doc):
                leaked.add(t)
    if leaked:
        raise SystemExit(f"public build would expose {len(leaked)} private names/IDs; not written")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(doc)
kb = OUT.stat().st_size / 1024
print(f"wrote {OUT}  ({kb:.0f} KB)")
for name in DATA:
    print(f"  embedded data/{name}.json")
