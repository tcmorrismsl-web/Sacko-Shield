/**
 * Live in-game scoring, for both platforms.
 *
 * Neither API is reachable from this sandbox, so both are stubbed with
 * payloads shaped like the real ones — including ESPN's `appliedStatTotal`,
 * which is where a defense's and every starter's running points actually live.
 * The point of this file is that the live path is exercised at all: the
 * previous poller only ever handled Sleeper, and nothing tested it.
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

// The week under test is whatever week the data is built for — never a
// hardcoded number. A fixture pinned to Week 3 is the same baked-in-week bug
// the app had, and it broke this suite the moment the data moved to Week 4.
const DW = Number(JSON.parse(fs.readFileSync(path.join(APP, "data/meta.json"), "utf8")).upcoming_week);
// Live points only count once a player's game has kicked off, so the clock is
// pinned to an hour into the earliest data-week game among the fixture teams.
// Using the real clock made this suite pass or fail depending on the day it ran.
const SCHED = JSON.parse(fs.readFileSync(path.join(APP, "data/schedule.json"), "utf8"));
const LIVE_AT = Math.min(...["BUF", "ATL", "MIN", "CIN"]
  .map(t => (SCHED.kickoffs[String(DW)] || {})[t])
  .filter(Boolean).map(g => Date.parse(g.kick))) + 3600e3;
// Half-PPR ESPN league, data week: team 3 (his) vs team 1, with points on the board.
const ESPN_LIVE = {
  schedule: [
    { id: 9, matchupPeriodId: DW - 1, home: { teamId: 1 }, away: { teamId: 3 } },
    { id: 11, matchupPeriodId: DW,
      home: { teamId: 3, totalPoints: 71.4, rosterForCurrentScoringPeriod: { entries: [
        { lineupSlotId: 0,  playerPoolEntry: { appliedStatTotal: 24.6,
            player: { id: 3918298, fullName: "Josh Allen", defaultPositionId: 1, proTeamId: 2 } } },
        { lineupSlotId: 2,  playerPoolEntry: { appliedStatTotal: 18.1,
            player: { id: 4430807, fullName: "Bijan Robinson", defaultPositionId: 2, proTeamId: 1 } } },
        // the defense, with points — the thing that was missing entirely
        { lineupSlotId: 16, playerPoolEntry: { appliedStatTotal: 11.0,
            player: { id: -16016, fullName: "Vikings D/ST", defaultPositionId: 16, proTeamId: 16 } } },
        // a bench player, to prove bench points don't become starters
        { lineupSlotId: 20, playerPoolEntry: { appliedStatTotal: 31.0,
            player: { id: 4361307, fullName: "Trey McBride", defaultPositionId: 4, proTeamId: 22 } } },
      ] } },
      away: { teamId: 1, totalPoints: 64.2, rosterForCurrentScoringPeriod: { entries: [
        { lineupSlotId: 0, playerPoolEntry: { appliedStatTotal: 9.4,
            player: { id: 4360234, fullName: "Evan McPherson", defaultPositionId: 5, proTeamId: 4 } } },
      ] } } },
  ],
};

const SLEEPER_LIVE = [
  { roster_id: 2, matchup_id: 5, points: 63.7,
    starters: ["12522", "9509"], players_points: { "12522": 21.4, "9509": 18.9 } },
  { roster_id: 9, matchup_id: 5, points: 22.6,
    starters: ["8183", "9224"], players_points: { "8183": 12.6, "9224": 10.0 } },
];

const stub = (espn, sleeper, mode) => `
window.__calls = [];
window.fetch = async (url) => {
  const u = String(url);
  window.__calls.push(u);
  if (${JSON.stringify(mode)} === "blocked")
    throw new TypeError("Failed to fetch");
  if (u.includes("fantasy.espn.com"))
    return { ok: true, status: 200, json: async () => (${JSON.stringify(espn)}) };
  if (u.includes("api.sleeper.app"))
    return { ok: true, status: 200, json: async () => (${JSON.stringify(sleeper)}) };
  throw new Error("unexpected host " + u);
};`;

const state = page => page.evaluate(() => ({
  live: !!S.livePoints,
  err: S.liveErr,
  can: S.canPollLive,
  pts: S.livePoints || {},
  pairs: ((S.league.matchups || {})[String(S.meta.upcoming_week)] || {}).pairs || [],
  byRoster: ((S.league.matchups || {})[String(S.meta.upcoming_week)] || {}).by_roster || {},
  scores: [...document.querySelectorAll("#p-matchup .score .pts")].map(e => e.textContent.trim()),
  statusTxt: (document.querySelector("#p-matchup .card") || {}).textContent || "",
  rows: document.querySelectorAll("#p-matchup .mrow").length,
}));

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
  await page.addInitScript(t => {
    const real = Date.now.bind(Date), off = t - real();
    Date.now = () => real() + off;
  }, LIVE_AT);
  page.on("pageerror", e => check("no page error", false, String(e)));
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => typeof S !== "undefined" && S.players.length > 0);

  // ---------- ESPN, mid-game ----------
  await page.evaluate(stub(ESPN_LIVE, SLEEPER_LIVE, "ok"));
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
  await page.click('#tabbar .tab:text-is("Matchup")').catch(() => {});
  await page.evaluate(() => pollLive());
  await page.waitForTimeout(400);
  let st = await state(page);

  check("ESPN live points arrive", st.live, `${Object.keys(st.pts).length} players scored`);
  check("…including the defense", st.pts.MIN === 11.0, `MIN = ${st.pts.MIN}`);
  check("…mapped onto our own player ids", st.pts["4984"] === 24.6,
    `Josh Allen = ${st.pts["4984"]}`);
  check("real ESPN pairings replace the shipped guess",
    st.pairs.length === 1 && st.pairs[0].rosters.sort().join(",") === "1,3",
    JSON.stringify(st.pairs));
  check("only this week's pairing is taken, not last week's", st.pairs.length === 1, `${st.pairs.length} pairs`);
  check("bench points don't make a bench player a starter",
    !(st.byRoster["3"].starters || []).includes("4361307"),
    `starters ${JSON.stringify(st.byRoster["3"].starters)}`);
  check("the card shows live scores, not projections",
    st.scores.join(" v ") === "71.4 v 64.2",
    `scores ${st.scores.join(" v ")}`);
  check("the status line says it is live", /live/i.test(st.statusTxt));

  // ---------- Sleeper, mid-game ----------
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "sleeper").key));
  await page.evaluate(() => pollLive());
  await page.waitForTimeout(400);
  st = await state(page);
  check("Sleeper live points arrive", st.live && st.pts["12522"] === 21.4,
    `12522 = ${st.pts["12522"]}`);
  check("switching league doesn't carry the other league's scores",
    st.pts.MIN === undefined, "ESPN points cleared");

  // ---------- before kickoff: all zeros is not "live" ----------
  await page.evaluate(stub(
    { schedule: [{ id: 11, matchupPeriodId: DW,
      home: { teamId: 3, totalPoints: 0, rosterForCurrentScoringPeriod: { entries: [
        { lineupSlotId: 0, playerPoolEntry: { appliedStatTotal: 0,
          player: { id: 3918298, fullName: "Josh Allen", defaultPositionId: 1, proTeamId: 2 } } }] } },
      away: { teamId: 1, totalPoints: 0, rosterForCurrentScoringPeriod: { entries: [] } } }] },
    SLEEPER_LIVE, "ok"));
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
  await page.evaluate(() => pollLive());
  await page.waitForTimeout(300);
  st = await state(page);
  check("an all-zero week is not reported as live", !st.live && st.can,
    `live=${st.live} connected=${st.can}`);
  check("…and says it is connected but nothing has scored",
    /nothing has scored/i.test(st.statusTxt));

  // ---------- blocked: degrade honestly, don't crash ----------
  await page.evaluate(stub(ESPN_LIVE, SLEEPER_LIVE, "blocked"));
  await page.evaluate(() => pollLive());
  await page.waitForTimeout(300);
  st = await state(page);
  check("a blocked call degrades to projections without throwing",
    !st.live && !st.can && !!st.err, `err=${st.err}`);
  check("…and says so plainly, naming the platform",
    /can't reach ESPN/i.test(st.statusTxt) && /aren't relayed/i.test(st.statusTxt),
    st.statusTxt.replace(/\s+/g, " ").slice(0, 90));
  check("the matchup still renders from projections", st.rows >= 8, `${st.rows} rows`);

  // ---------- polling pauses when the phone is pocketed ----------
  const paced = await page.evaluate(() => {
    const before = document.hidden;
    Object.defineProperty(document, "hidden", { value: true, configurable: true });
    scheduleLive();
    const stopped = _liveTimer === null || _liveTimer === undefined;
    Object.defineProperty(document, "hidden", { value: before, configurable: true });
    return stopped;
  });
  check("polling stops while the page is hidden", paced);

  await browser.close(); srv.close();
  const bad = results.filter(r => !r.pass);
  console.log(`\n${results.length - bad.length}/${results.length} checks passed`);
  if (bad.length) { console.log("FAILURES:", bad.map(b => b.name)); process.exit(1); }
  console.log("LIVE SCORING WORKS ON BOTH PLATFORMS");
})();
