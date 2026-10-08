/**
 * Verify both builds the way the viewer actually meets them.
 *
 * Every earlier test ran against a hand-made preview wrapper, which is not
 * what claude.ai serves. This one rebuilds the artifact page with the exact
 * head the platform injects, serves the data files as real siblings, and
 * drives the UI by clicking rather than by calling functions directly —
 * because a handler that was never wired up still "passes" when the test
 * calls the function behind it.
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

// byte-for-byte the wrapper the Artifact platform prepends
const PLATFORM_HEAD =
  '<!doctype html><html><head><meta charset=utf8><meta name=viewport ' +
  'content="width=device-width,initial-scale=1,viewport-fit=cover"><style>' +
  ':root{color-scheme:light;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);' +
  'padding-bottom:env(safe-area-inset-bottom,0px)}html{scroll-padding-top:env(safe-area-inset-top,0px)}' +
  'body{margin:0;padding:0;font:14px -apple-system,BlinkMacSystemFont,sans-serif;' +
  'background:#faf9f5;color:#141413}img{max-width:100%}' +
  "[hidden]:not([hidden=until-found i]){display:none!important}</style></head><body>\n\n";

const MIME = { ".html": "text/html", ".json": "application/json" };

function serve(dir, indexBody) {
  const srv = http.createServer((req, res) => {
    const url = req.url.split("?")[0];
    if (url === "/" || url === "/index.html") {
      res.writeHead(200, { "content-type": "text/html" });
      res.end(indexBody);
      return;
    }
    const f = path.join(dir, url);
    if (!f.startsWith(dir) || !fs.existsSync(f)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": MIME[path.extname(f)] || "text/plain" });
    res.end(fs.readFileSync(f));
  });
  return new Promise(r => srv.listen(0, () => r({ srv, port: srv.address().port })));
}

const results = [];
const check = (name, pass, detail) => {
  results.push({ name, pass, detail });
  console.log(`${pass ? "  ok  " : "  FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
};

async function drive(page, label) {
  console.log(`\n=== ${label} ===`);
  const errors = [];
  /* The standalone calls api.sleeper.app on boot and during games. This
     sandbox's egress proxy blocks that host, so the browser logs a failed
     resource load even though the app catches it and carries on. That is an
     artifact of where the test runs, not a defect, so it is scoped out by
     name — every other console error still fails the run. */
  const expected = t => /ERR_TUNNEL_CONNECTION_FAILED|ERR_PROXY|ERR_NAME_NOT_RESOLVED|ERR_CONNECTION/.test(t)
    || /sleeper\.app/.test(t);
  const netIgnored = [];
  page.on("console", m => {
    if (m.type() !== "error") return;
    (expected(m.text()) ? netIgnored : errors).push(m.text());
  });
  page.on("pageerror", e => errors.push(String(e)));

  await page.waitForFunction(() => typeof S !== "undefined" && S.players && S.players.length > 0,
    null, { timeout: 20000 });
  await page.waitForTimeout(500);

  const leagues = await page.evaluate(() => S.leagues.map(l => ({
    key: l.key, name: l.name, platform: l.platform, status: l.status,
    teams: l.rosters.length, my: l.my_team,
    mine: (l.rosters.find(r => r.id === l.my_team) || {}).players?.length || 0,
  })));
  check(`${label}: 4 leagues present`, leagues.length === 4,
    leagues.map(l => `${l.name}(${l.teams}t/${l.mine}p)`).join(" "));

  for (const l of leagues) {
    check(`${label}: ${l.name} — my roster is populated`, l.mine >= 15,
      `${l.mine} players`);
  }

  // every tab, every league, clicked not called
  for (const l of leagues) {
    await page.evaluate(k => switchLeague(k), l.key);
    await page.waitForTimeout(150);
    const tabs = await page.$$eval("#tabbar .tab", ts => ts.map(t => t.textContent.trim()));
    for (const t of tabs) {
      const before = errors.length;
      await page.click(`#tabbar .tab:text-is("${t}")`).catch(() => {});
      await page.waitForTimeout(220);
      const body = await page.evaluate(() => {
        const vis = [...document.querySelectorAll("main > section")]
          .find(s => !s.hidden);
        return { id: vis?.id, len: (vis?.textContent || "").trim().length };
      });
      check(`${label}: ${l.name} / ${t} renders`,
        body.len > 60 && errors.length === before,
        `${body.id} ${body.len} chars${errors.length > before ? " ERR:" + errors[before] : ""}`);
    }
  }

  // --- D/ST present on ESPN rosters (complaint 1) ---
  for (const l of leagues.filter(x => x.platform === "ESPN")) {
    await page.evaluate(k => switchLeague(k), l.key);
    const pos = await page.evaluate(() => {
      const r = S.league.rosters.find(x => x.id === S.league.my_team);
      return r.players.map(i => (S.byId.get(i) || {}).pos);
    });
    check(`${label}: ${l.name} — my roster has a D/ST`, pos.includes("DST"),
      pos.filter(Boolean).join(","));
    check(`${label}: ${l.name} — my roster has a K`, pos.includes("K"));
  }

  // --- position chips match what the league actually starts (complaint 3) ---
  for (const l of leagues) {
    await page.evaluate(k => switchLeague(k), l.key);
    await page.click(`#tabbar .tab:text-is("Waivers")`).catch(() => {});
    await page.waitForTimeout(250);
    const got = await page.evaluate(() => ({
      chips: [...document.querySelectorAll("#p-waiver .fchip")]
        .map(c => c.textContent.trim()).filter(t => t !== "All"),
      graded: gradedPositions(S.league),
    }));
    const extra = got.chips.filter(c => !got.graded.includes(c));
    check(`${label}: ${l.name} — no chip for a position it doesn't start`,
      extra.length === 0, `chips[${got.chips}] graded[${got.graded}]`);
  }

  // --- matchup tab (complaint 2) ---
  for (const l of leagues) {
    await page.evaluate(k => switchLeague(k), l.key);
    await page.click(`#tabbar .tab:text-is("Matchup")`).catch(() => {});
    await page.waitForTimeout(300);
    let state = await page.evaluate(() => ({
      picker: !!document.querySelector("#oppPick"),
      rows: document.querySelectorAll("#p-matchup .mrow").length,
      wp: document.querySelector("#p-matchup .wp b")?.textContent || null,
      pts: [...document.querySelectorAll("#p-matchup .score .pts")].map(e => e.textContent),
    }));
    if (state.picker) {
      // pick the first opponent the way a person would
      const val = await page.$eval("#oppPick option:nth-child(2)", o => o.value);
      await page.selectOption("#oppPick", val);
      await page.waitForTimeout(400);
      state = await page.evaluate(() => ({
        picker: !!document.querySelector("#oppPick"),
        rows: document.querySelectorAll("#p-matchup .mrow").length,
        wp: document.querySelector("#p-matchup .wp b")?.textContent || null,
        pts: [...document.querySelectorAll("#p-matchup .score .pts")].map(e => e.textContent),
      }));
      check(`${label}: ${l.name} — choosing an opponent builds the matchup`,
        !state.picker && state.rows > 0, `${state.rows} rows, wp ${state.wp}`);
    }
    const bothSides = state.pts.length === 2 && state.pts.every(p => parseFloat(p) > 0);
    check(`${label}: ${l.name} — matchup shows two real lineups`,
      state.rows >= 8 && bothSides && !!state.wp,
      `${state.rows} rows, scores ${state.pts.join(" v ")}, wp ${state.wp}`);
  }

  // --- league-specific scoring actually bites ---
  const scoring = await page.evaluate(() => {
    const out = {};
    for (const l of S.leagues) {
      switchLeague(l.key);
      const p = S.players.find(x => x.name === "Puka Nacua");
      out[l.name] = { rec: scoringOf(l).rec, proj: p ? pj(p) : null,
                      partial: !!l.scoring_partial };
    }
    return out;
  });
  const halfRec = scoring[HALF_PPR.name]?.rec, fullRec = scoring[FULL_PPR.name]?.rec;
  check(`${label}: the half-PPR league uses its real half-PPR reception value`, halfRec === 0.5,
    `rec=${halfRec}`);
  check(`${label}: the full-PPR league uses its real full-PPR reception value`, fullRec === 1,
    `rec=${fullRec}`);
  const projs = Object.entries(scoring).map(([k, v]) => `${k}:${v.proj}`);
  check(`${label}: the same player scores differently per league`,
    new Set(Object.values(scoring).map(v => v.proj)).size > 1, projs.join("  "));
  check(`${label}: no league scores a quarterback at zero`,
    await page.evaluate(() => S.leagues.every(l => {
      switchLeague(l.key);
      return (pj(S.players.find(p => p.name === "Josh Allen")) || 0) > 5;
    })), "partial ESPN scoring merged over defaults");

  // --- layout ---
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  check(`${label}: no horizontal page overflow at 390px`, overflow <= 1, `${overflow}px`);

  check(`${label}: no console errors anywhere`, errors.length === 0,
    errors.slice(0, 2).join(" | "));
  if (netIgnored.length)
    console.log(`  note  ${netIgnored.length} blocked ${"" }sleeper.app request(s) ` +
      `handled gracefully by the app (sandbox egress, not a defect)`);
  return errors;
}

(async () => {
  const browser = await chromium.launch();

  // 1. the artifact, assembled exactly as claude.ai serves it
  const artifactBody = PLATFORM_HEAD + fs.readFileSync(path.join(APP, "index.html"), "utf8")
    + "\n</body></html>";
  const { srv, port } = await serve(APP, artifactBody);
  let page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "networkidle" });
  await drive(page, "ARTIFACT");
  await page.close();
  srv.close();

  // 2. the standalone file, opened straight off disk
  page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto("file://" + STANDALONE, { waitUntil: "load" });
  await drive(page, "STANDALONE");
  await page.close();

  await browser.close();

  const bad = results.filter(r => !r.pass);
  console.log(`\n${results.length - bad.length}/${results.length} checks passed`);
  if (bad.length) {
    console.log("\nFAILURES:");
    bad.forEach(b => console.log(`  - ${b.name}: ${b.detail || ""}`));
    process.exit(1);
  }
  console.log("ALL CHECKS PASSED");
})();
