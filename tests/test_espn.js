/**
 * Exercise the ESPN read path that only the viewer's browser can take.
 *
 * This sandbox is blocked from ESPN, so `tryEspn()` had never once been run
 * against a real payload — and it was broken. Every skill player matched and
 * every DEFENSE was dropped, because ESPN names a defense "Vikings D/ST" and
 * gives it a negative player id, while the database keys it "MIN" and carries
 * no ESPN id for it at all. A roster came back looking complete with an empty
 * D/ST slot, which is exactly what the user kept reporting.
 *
 * `fetch` is stubbed with payloads shaped like ESPN's so the path runs here.
 */
const { chromium } = require("playwright");
const http = require("http");
const fs = require("fs");
const path = require("path");

const APP = "/home/claude/app";
const HEAD = fs.readFileSync("/home/claude/head.txt", "utf8");
const MIME = { ".html": "text/html", ".json": "application/json" };

const results = [];
const check = (name, pass, detail) => {
  results.push({ name, pass });
  console.log(`${pass ? "  ok  " : "  FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

// A sample league: half PPR, 4pt passing TD, one team carrying a defense.
const PAYLOAD = {
  settings: {
    name: "Sample League",
    rosterSettings: { lineupSlotCounts: { 0: 1, 2: 2, 4: 2, 6: 1, 16: 1, 17: 1, 20: 7, 23: 1 } },
    scoringSettings: { scoringItems: [
      { statId: 3, points: 0.04 }, { statId: 4, points: 4 }, { statId: 20, points: -2 },
      { statId: 24, points: 0.1 }, { statId: 25, points: 6 },
      { statId: 42, points: 0.1 }, { statId: 43, points: 6 },
      { statId: 53, points: 0.5 }, { statId: 72, points: -2 },
      { statId: 80, points: 3 }, { statId: 77, points: 4 }, { statId: 198, points: 5 },
      { statId: 86, points: 1 }, { statId: 85, points: -1 }, { statId: 88, points: -1 },
    ] },
  },
  teams: [{ id: 3, name: "Team Three", primaryOwner: "X",
            record: { overall: { wins: 1, losses: 1, pointsFor: 247.48 } } }],
  members: [{ id: "X", displayName: "owner3" }],
};

// lineupSlotId : ESPN player object
const ROSTER = [
  [0,  { id: 3918298, fullName: "Josh Allen",       defaultPositionId: 1, proTeamId: 2 }],
  [2,  { id: 4430807, fullName: "Bijan Robinson",   defaultPositionId: 2, proTeamId: 1 }],
  [4,  { id: 4362628, fullName: "Justin Jefferson", defaultPositionId: 3, proTeamId: 16 }],
  [6,  { id: 4361307, fullName: "Trey McBride",     defaultPositionId: 4, proTeamId: 22 }],
  // the defense, exactly as ESPN sends it: negative id, nickname + D/ST
  [16, { id: -16016,  fullName: "Vikings D/ST",     defaultPositionId: 16, proTeamId: 16 }],
  [17, { id: 4360234, fullName: "Evan McPherson",   defaultPositionId: 5, proTeamId: 4 }],
];

const espnStub = (payload, roster) => `
window.fetch = async (url) => {
  const u = String(url);
  if (!u.includes("fantasy.espn.com")) throw new Error("unexpected host " + u);
  const P = ${JSON.stringify(payload)}, R = ${JSON.stringify(roster)};
  let body;
  if (u.includes("view=mRoster")) {
    body = { teams: [{ id: 3, roster: { entries: R.map(([slot, pl]) => ({
      lineupSlotId: slot, playerPoolEntry: { player: pl } })) } }] };
  } else if (u.includes("view=mSettings")) {
    body = { settings: P.settings };
  } else if (u.includes("view=mTeam")) {
    body = { teams: P.teams, members: P.members };
  } else {
    body = { settings: P.settings, teams: P.teams, members: P.members };
  }
  return { ok: true, status: 200, json: async () => body };
};`;

(async () => {
  const body = HEAD + fs.readFileSync(path.join(APP, "index.html"), "utf8")
    + "\n</body></html>";
  const srv = http.createServer((req, res) => {
    const u = req.url.split("?")[0];
    if (u === "/") { res.writeHead(200, { "content-type": "text/html" }); return res.end(body); }
    const f = path.join(APP, u);
    if (!fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": MIME[path.extname(f)] || "text/plain" });
    res.end(fs.readFileSync(f));
  });
  await new Promise(r => srv.listen(0, r));
  const port = srv.address().port;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => typeof S !== "undefined" && S.players.length > 0);

  // --- the matcher, on the exact shapes ESPN sends ---
  const m = await page.evaluate(() => {
    const t = e => { const p = matchEspn(e); return p ? p.id + "/" + p.pos : null; };
    return {
      named:  t({ playerPoolEntry: { player: { id: -16016, fullName: "Vikings D/ST",
                  defaultPositionId: 16, proTeamId: 16 } } }),
      noTeam: t({ playerPoolEntry: { player: { id: -16016, fullName: "Vikings D/ST",
                  defaultPositionId: 16 } } }),
      odd:    t({ playerPoolEntry: { player: { id: -16023, fullName: "Steelers D/ST",
                  defaultPositionId: 16, proTeamId: 23 } } }),
      // our ids are Sleeper ids, so the invariant is that the matched player
      // CARRIES the espn id we were handed — not that the ids are equal
      skill:  (() => {
        const pl = { id: 4262921, fullName: "Justin Jefferson",
                     defaultPositionId: 3, proTeamId: 16 };
        const hit = matchEspn({ playerPoolEntry: { player: pl } });
        return hit ? `${hit.name}|${hit.espn === String(pl.id)}` : null;
      })(),
    };
  });
  check("ESPN defense resolves by pro-team id", m.named === "MIN/DST", `got ${m.named}`);
  check("…and by its negative id when proTeamId is absent", m.noTeam === "MIN/DST", `got ${m.noTeam}`);
  check("…for a second team, to rule out a coincidence", m.odd === "PIT/DST", `got ${m.odd}`);
  check("skill players still match, by their ESPN id",
    m.skill === "Justin Jefferson|true", `got ${m.skill}`);

  // --- the whole fetch path ---
  await page.evaluate(espnStub(PAYLOAD, ROSTER));
  const lg = await page.evaluate(async () => {
    const l = await tryEspn("100001", 2026);
    const r = l.rosters[0];
    return {
      status: l.status, scoring: l.scoring, partial: !!l.scoring_partial,
      rec: l.scoring_settings && l.scoring_settings.rec,
      passTd: l.scoring_settings && l.scoring_settings.pass_td,
      pos: r.players.map(i => (S.byId.get(i) || {}).pos),
      starters: r.starters.length,
    };
  });
  check("a league loaded from ESPN comes back with rosters", lg.status === "full", lg.status);
  check("its roster includes the D/ST", lg.pos.includes("DST"), lg.pos.join(","));
  check("it carries ESPN's real scoring, not the defaults",
    lg.partial && lg.rec === 0.5 && lg.passTd === 4,
    `partial=${lg.partial} rec=${lg.rec} passTd=${lg.passTd}`);
  check("the D/ST is in the starting lineup", lg.starters === 6, `${lg.starters} starters`);

  // --- and the guard, if defenses ever vanish again ---
  await page.evaluate(espnStub(PAYLOAD, ROSTER.filter(([slot]) => slot !== 16)));
  const guarded = await page.evaluate(async () => {
    const l = await tryEspn("100001", 2026);
    return { status: l.status, note: l.note };
  });
  check("a fetch that loses every defense is refused, not trusted",
    guarded.status === "standings_only",
    guarded.note ? guarded.note.slice(0, 58) + "…" : guarded.status);

  await browser.close(); srv.close();
  const bad = results.filter(r => !r.pass);
  console.log(`\n${results.length - bad.length}/${results.length} checks passed`);
  if (bad.length) { console.log("FAILURES:", bad.map(b => b.name)); process.exit(1); }
  console.log("ESPN READ PATH FIXED");
})();
