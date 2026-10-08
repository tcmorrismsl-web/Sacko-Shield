/**
 * "Not pulling the current week" — every path to it, tested.
 *
 * What was wrong, each verified before this was written:
 *  - the week was baked in at build time, so a copy built for Week 3 showed
 *    Week 3 as current forever, with nothing on screen to say so;
 *  - a hand-picked ESPN opponent carried over from one week to the next;
 *  - picking an opponent saved every roster too, which reloaded as a "paste";
 *  - kickoff times were Eastern wall-clock stamped as UTC, 4 hours early.
 *
 * The clock is moved rather than waited for: Date.now is offset per scenario,
 * which is all the week logic reads.
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
const STANDALONE = "/mnt/user-data/outputs/sacko-shield.html";
const HEAD = fs.readFileSync("/home/claude/head.txt", "utf8");
const MIME = { ".html": "text/html", ".json": "application/json" };
const SCHED = JSON.parse(fs.readFileSync(path.join(APP, "data/schedule.json"), "utf8"));
const META = JSON.parse(fs.readFileSync(path.join(APP, "data/meta.json"), "utf8"));
const DW = Number(META.upcoming_week);

const results = [];
const check = (name, pass, detail) => {
  results.push({ name, pass });
  console.log(`${pass ? "  ok  " : "  FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

// the last game of the data week ends at...
const lastEnd = Math.max(...Object.values(SCHED.kickoffs[String(DW)]).map(g => Date.parse(g.end)));
const firstKick = Math.min(...Object.values(SCHED.kickoffs[String(DW)]).map(g => Date.parse(g.kick)));
const DURING = firstKick + 3600e3;                 // an hour into the data week
const JUST_BEFORE_END = lastEnd - 5 * 60e3;
const JUST_AFTER_END = lastEnd + 5 * 60e3;

async function open(browser, url, at, seed) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 900 } });
  await ctx.addInitScript(t => {
    const real = Date.now.bind(Date), off = t - real();
    Date.now = () => real() + off;
  }, at);
  if (seed) await ctx.addInitScript(v => {
    try { localStorage.setItem("sacko.rosters", v); } catch {}
  }, seed);
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", e => errs.push(String(e)));
  await page.goto(url, { waitUntil: "load" });
  await page.waitForFunction(() => typeof S !== "undefined" && S.players && S.players.length > 0);
  await page.waitForTimeout(300);
  return { page, ctx, errs };
}

const state = page => page.evaluate(() => ({
  clock: clockWeek(), data: dataWeek(), stale: staleWeek(),
  banner: ($("#staleBanner") || {}).textContent || "",
  rows: document.querySelectorAll("#p-matchup .mrow").length,
  picker: !!document.querySelector("#oppPick"),
  matchupText: ($("#p-matchup") || {}).textContent || "",
  pasteBanner: /Working from the roster you pasted in/.test(
    [...document.querySelectorAll("main section")].map(x => x.textContent).join(" ")),
}));

(async () => {
  const body = HEAD + fs.readFileSync(path.join(APP, "index.html"), "utf8") + "\n</body></html>";
  const srv = http.createServer((req, res) => {
    const u = req.url.split("?")[0];
    if (u === "/") { res.writeHead(200, { "content-type": "text/html" }); return res.end(body); }
    const f = path.join(APP, u);
    if (!fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": MIME[path.extname(f)] || "text/plain" });
    res.end(fs.readFileSync(f));
  });
  await new Promise(r => srv.listen(0, r));
  const URL = `http://127.0.0.1:${srv.address().port}/`;
  const browser = await chromium.launch();

  console.log(`data week ${DW}; its first kickoff ${new Date(firstKick).toISOString()}, last game ends ${new Date(lastEnd).toISOString()}\n`);

  // ---------- kickoff times are real UTC
  const tnf = Object.values(SCHED.kickoffs["4"]).map(g => g.kick).sort()[0];
  check("Week 4 opens Friday 00:15Z (Thursday 8:15pm Eastern), not 20:15Z", tnf === "2026-10-02T00:15:00Z", tnf);

  // ---------- during the week: current, no banner, matchup renders
  let { page, ctx, errs } = await open(browser, URL, DURING);
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "sleeper").key));
  await page.click('#tabbar .tab:text-is("Matchup")').catch(() => {});
  await page.waitForTimeout(300);
  let st = await state(page);
  check("mid-week: the clock and the data agree", st.clock === DW && st.stale === null, `clock ${st.clock}, data ${st.data}`);
  check("mid-week: no stale banner", st.banner.trim() === "", st.banner.slice(0, 40));
  check("mid-week: the matchup renders", st.rows >= 8, `${st.rows} rows`);
  check("no page errors", !errs.length, errs[0]);
  await ctx.close();

  // ---------- the exact boundary, which only lands right if kickoffs are UTC
  ({ page, ctx } = await open(browser, URL, JUST_BEFORE_END));
  st = await state(page);
  check("5 min before the last game of the week ends, it is still that week", st.clock === DW && !st.stale, `clock ${st.clock}`);
  await ctx.close();
  ({ page, ctx } = await open(browser, URL, JUST_AFTER_END));
  st = await state(page);
  check("5 min after it ends, the next week has begun", st.clock === DW + 1 && st.stale === DW + 1, `clock ${st.clock}`);
  await ctx.close();

  // ---------- after the week turns: every tab says so, matchup refuses to pose
  ({ page, ctx, errs } = await open(browser, URL, JUST_AFTER_END + 10 * 3600e3));
  const tabs = await page.$$eval("#tabbar .tab", ts => ts.map(t => t.textContent.trim()));
  const missing = [];
  for (const t of tabs) {
    await page.click(`#tabbar .tab:text-is("${t}")`);
    await page.waitForTimeout(150);
    const b = await page.evaluate(() => ($("#staleBanner") || {}).textContent || "");
    if (!new RegExp(`Week ${DW} is over`).test(b)) missing.push(t);
  }
  check("stale: the banner is on every tab", !missing.length, missing.length ? "missing on " + missing : `${tabs.length} tabs`);
  await page.click('#tabbar .tab:text-is("Matchup")');
  await page.waitForTimeout(200);
  st = await state(page);
  check("stale: the matchup shows no last-week game as current", st.rows === 0 && /Week \d+ is over/.test(st.matchupText),
    `${st.rows} rows`);
  const calls = await page.evaluate(async () => {
    let n = 0; const real = window.fetch;
    window.fetch = (...a) => { n++; return real(...a); };
    await pollLive(); window.fetch = real; return n;
  });
  check("stale: no poll for a finished week", calls === 0, `${calls} fetches`);
  check("stale: the published page points to the scheduled rebuild",
    /next scheduled rebuild/.test(st.banner));
  check("no page errors", !errs.length, errs[0]);
  await ctx.close();

  // ---------- the copy he had: built for Week 3, opened during Week 4
  ({ page, ctx } = await open(browser, URL, DURING));
  await page.evaluate(() => { S.meta.upcoming_week = 3; show(S.tab); });
  st = await state(page);
  check("a Week 3 copy opened in Week 4 says so", /Week 3 is over — it's Week 4 now/.test(st.banner),
    st.banner.replace(/\s+/g, " ").slice(0, 60));
  await ctx.close();

  // ---------- week-scoped opponent (the half-PPR league has no shipped Week 4 pairing)
  const seed = obj => JSON.stringify({ map: { [HALF_PPR.key]: obj }, savedAt: new Date().toISOString() });
  for (const [label, entry, wantPicker] of [
    ["a pick saved before picks were week-stamped is not reused", { __opponent: "6" }, true],
    ["last week's pick is not reused this week", { __opponent: "6", __opponentWeek: DW - 1 }, true],
    ["this week's pick is used", { __opponent: "6", __opponentWeek: DW }, false],
  ]) {
    ({ page, ctx } = await open(browser, URL, DURING, seed(entry)));
    await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
    await page.click('#tabbar .tab:text-is("Matchup")').catch(() => {});
    await page.waitForTimeout(250);
    st = await state(page);
    check(label, wantPicker ? (st.picker && st.rows === 0) : (!st.picker && st.rows > 0),
      `picker=${st.picker} rows=${st.rows}`);
    await ctx.close();
  }

  // ---------- picking an opponent is not pasting a roster
  ({ page, ctx } = await open(browser, URL, DURING));
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
  await page.click('#tabbar .tab:text-is("Matchup")');
  await page.waitForTimeout(250);
  await page.selectOption("#oppPick", "6");
  await page.waitForTimeout(300);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("sacko.rosters") || "null"));
  const lgSaved = saved && saved.map && saved.map[HALF_PPR.key];
  const rosterKeys = lgSaved ? Object.keys(lgSaved).filter(k => !k.startsWith("__")) : ["<none saved>"];
  check("a pick saves the pick and its week, and no rosters",
    lgSaved && lgSaved.__opponent === "6" && Number(lgSaved.__opponentWeek) === DW && rosterKeys.length === 0,
    JSON.stringify(lgSaved));
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => typeof S !== "undefined" && S.players.length > 0);
  await page.evaluate(() => switchLeague(S.leagues.find(l => l.source === "espn" && l.scoring === "half").key));
  await page.click('#tabbar .tab:text-is("Matchup")');
  await page.waitForTimeout(250);
  st = await state(page);
  check("…and after a reload the pick holds", !st.picker && st.rows > 0, `${st.rows} rows`);
  check("…without claiming a roster was pasted", !st.pasteBanner);
  await ctx.close();

  // ---------- the downloaded copy, stale, points to the claude.ai page
  ({ page, ctx } = await open(browser, "file://" + STANDALONE, JUST_AFTER_END + 10 * 3600e3));
  st = await state(page);
  check("stale downloaded copy says it never updates itself",
    /A downloaded copy never updates itself/.test(st.banner), st.banner.replace(/\s+/g, " ").slice(0, 70));
  await ctx.close();

  await browser.close(); srv.close();
  const bad = results.filter(r => !r.pass);
  console.log(`\n${results.length - bad.length}/${results.length} checks passed`);
  if (bad.length) { console.log("FAILURES:", bad.map(b => b.name)); process.exit(1); }
  console.log("CURRENT-WEEK HANDLING VERIFIED");
})();
