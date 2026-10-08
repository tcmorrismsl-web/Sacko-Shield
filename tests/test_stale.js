/**
 * Reproduce the reported failure, then prove it is fixed.
 *
 * The user saw "no defense" on his ESPN roster through several rounds of fixes
 * that were all correct in the shipped data. The cause was a roster he pasted
 * in early on, kept in browser storage and in the artifact's own store, which
 * `applyManual` laid over the real rosters on every single load. If that paste
 * had no D/ST, the D/ST slot stayed empty forever.
 *
 * This plants exactly that state and checks the defense survives it.
 */
const { chromium } = require("playwright");
const http = require("http");
const fs = require("fs");
const path = require("path");

const APP = "/home/claude/app";

// Leagues are found by shape from the local, git-ignored leagues.json, so no
// league IDs or names live in the repo. HALF_PPR = the 8-team half-PPR ESPN league.
const LEAGUES_LOCAL = JSON.parse(fs.readFileSync(path.join(APP, "data/leagues.json"), "utf8"));
const HALF_PPR = LEAGUES_LOCAL.find(l => l.source === "espn" && l.scoring === "half");
const FULL_PPR = LEAGUES_LOCAL.find(l => l.source === "espn" && l.scoring === "ppr");
const HEAD = fs.readFileSync("/home/claude/head.txt", "utf8");
const MIME = { ".html": "text/html", ".json": "application/json" };

const results = [];
const check = (name, pass, detail) => {
  results.push({ name, pass });
  console.log(`${pass ? "  ok  " : "  FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

const probe = page => page.evaluate(() => {
  const lg = S.leagues.find(l => l.source === "espn" && l.scoring === "half");
  const r = lg.rosters.find(x => x.id === lg.my_team);
  const pos = r.players.map(i => (S.byId.get(i) || {}).pos).filter(Boolean);
  const slots = [...document.querySelectorAll("#p-week .slot")].map(s => ({
    lbl: s.querySelector(".slot-lbl")?.textContent.trim(),
    txt: s.textContent.replace(/\s+/g, " ").trim().slice(0, 60),
  }));
  return {
    hasDST: pos.includes("DST"),
    n: r.players.length,
    applied: !!lg.manual_applied,
    available: !!lg.manual_available,
    banner: !!document.querySelector("#p-week .banner"),
    resetBtn: !!document.querySelector("#p-week [data-shipped]"),
    dstSlot: slots.find(s => s.lbl === "D/ST")?.txt || null,
  };
});

async function open(browser, port, seed) {
  const page = await browser.newPage({ viewport: { width: 390, height: 900 } });
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
  if (seed) {
    await page.evaluate(s => localStorage.setItem("sacko.rosters", s), seed);
    await page.reload({ waitUntil: "networkidle" });
  }
  await page.waitForFunction(() => typeof S !== "undefined" && S.players.length > 0);
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
  // by role, not label: the label carries the week number, which changes weekly
  await page.click('#tabbar .tab[data-tab="week"]');
  await page.waitForTimeout(400);
  return page;
}

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

  // --- baseline: nothing stored ---
  let page = await open(browser, port, null);
  let st = await probe(page);
  check("clean browser: D/ST on the roster", st.hasDST, `${st.n} players, slot "${st.dstSlot}"`);
  await page.close();

  // --- the reported state: an old paste with no defense, legacy bare-map shape ---
  const stale = JSON.stringify({
    [HALF_PPR.key]: { "3": ["9509", "4984", "6794", "8137", "11584", "6801",
                           "2216", "10222", "9756", "4037", "12534"] },
  });
  page = await open(browser, port, stale);
  st = await probe(page);
  check("stale paste (no D/ST) does NOT override shipped rosters", st.hasDST,
    `${st.n} players, applied=${st.applied}, slot "${st.dstSlot}"`);
  check("stale paste is offered back rather than silently dropped", st.available);
  await page.close();

  // --- a paste made AFTER this build should still win ---
  const built = JSON.parse(fs.readFileSync(path.join(APP, "data/meta.json"), "utf8")).built;
  const fresh = JSON.stringify({
    map: JSON.parse(stale),
    savedAt: new Date(Date.parse(built) + 60000).toISOString(),
  });
  page = await open(browser, port, fresh);
  st = await probe(page);
  check("a paste newer than the build still takes effect", st.applied && !st.hasDST,
    `${st.n} players, applied=${st.applied}`);
  check("and it says so, with a one-tap way back", st.banner && st.resetBtn);

  // --- clicking the way back restores the shipped roster ---
  await page.click("#p-week [data-shipped]");
  await page.waitForTimeout(500);
  st = await probe(page);
  check("tapping “Use ESPN's roster” brings the defense back", st.hasDST,
    `${st.n} players, slot "${st.dstSlot}"`);
  await page.close();

  await browser.close(); srv.close();

  const bad = results.filter(r => !r.pass);
  console.log(`\n${results.length - bad.length}/${results.length} checks passed`);
  if (bad.length) { console.log("FAILURES:", bad.map(b => b.name)); process.exit(1); }
  console.log("STALE-STATE REGRESSION FIXED");
})();
