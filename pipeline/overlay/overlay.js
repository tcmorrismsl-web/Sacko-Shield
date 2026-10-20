/* ------------------------------------------------------------ fresh overlay
   Inlined into the public build by build_standalone.py --public.

   A GitHub job (pipeline/overlay/refresh.py) rebuilds overlay.json every 15
   minutes before kickoffs, every 30 during games and every 2 hours otherwise.
   It carries NFL-wide data only — Sleeper's projected stat lines, injury
   designations and practice participation, kickoff-window weather, the
   FantasyPros weekly consensus, Sleeper trending — and this lays it over the
   data baked into the page, on open and every 15 minutes while the page is
   visible.

   Rules, each because the failure is silent otherwise:
   - The overlay never moves the app BACKWARDS: an overlay for an earlier week
     than the page's own data is ignored.
   - Application is idempotent: every field is reset from the page's own
     baseline (p._base) before the overlay is laid on, so applying twice, or
     applying a newer overlay, never compounds a weather multiplier.
   - "Sleeper projects nothing" is only believed for a position whose pull
     actually succeeded (overlay.proj_positions); a failed pull leaves the
     page's own line alone.
   - Weather multiplies only outdoor games, and only stats whose effect was
     measured (passing/receiving yards, TDs, receptions, field goals).
     Rushing is untouched; retractable roofs show the forecast unadjusted. */

const OVERLAY_URL = "https://raw.githubusercontent.com/tcmorrismsl-web/Sacko-Shield/data/overlay.json";
const OVERLAY_EVERY_MS = 15 * 60e3;
const OVERLAY_TIMEOUT_MS = 6000;
let _ovTimer = null, _ovInFlight = false;

/* which multiplier each stat key takes */
function wxKind(k) {
  if (/^(pass_yd|rec_yd|pass_fd|rec_fd)$/.test(k)) return "yd";
  if (/^(pass_td|rec_td)$/.test(k)) return "td";
  if (/^(rec|pass_cmp|bonus_rec_(te|rb|wr)|rec_\d+_\d+|rec_40p)$/.test(k)) return "rec";
  if (/^(fga|fgm|fgm_\d+_\d+|fgm_50p|fgm_yds|fgmiss|fgmiss_\d+_\d+|fgmiss_50p)$/.test(k)) return "fg";
  return null;
}

function weatherLine(line, mult) {
  if (!line || !mult) return line;
  const out = {};
  for (const k in line) {
    const kind = wxKind(k);
    out[k] = kind && mult[kind] != null ? Math.round(line[k] * mult[kind] * 1000) / 1000 : line[k];
  }
  return out;
}

const pprOf = line => {
  const v = scoreLine(line, DEFAULT_SCORING);
  return v == null ? null : Math.round(v * 100) / 100;
};

const BASE_KEYS = ["pstats", "pstats_src", "proj", "proj_src", "inj", "inj_note", "inj_week",
  "wk_ecr", "wk_pos_rank", "wk_grade", "wk_proj", "opp", "home", "wk_opp", "dst_ctx"];

function applyOverlay(ov) {
  if (!ov || ov.v !== 1 || !ov.proj) return false;
  if (Number(ov.season) !== Number(S.meta.season)) return false;
  if (!S._baseWeek) S._baseWeek = Number(S.meta.upcoming_week);
  const wk = Number(ov.week);
  if (!(wk >= S._baseWeek)) return false;               // never go backwards
  const advanced = wk > S._baseWeek;

  // week, kickoffs, and the injury report's week
  S.meta.upcoming_week = wk;
  S.kick = Object.assign({}, S.kick, { [String(wk)]: ov.kickoffs });
  S.meta.sources = Object.assign({}, S.meta.sources, { injuries_week: wk });
  const ex = ov.experts || {};
  if (Object.keys(ex).length) S.meta.weekly_covers_week = wk;
  const okPos = new Set(ov.proj_positions || []);
  const kick = ov.kickoffs || {};
  const kickComplete = Object.keys(kick).length >= 24;   // 32 teams less at most 8 on bye

  for (const p of S.players) {
    if (!p._base) p._base = Object.fromEntries(BASE_KEYS.map(k =>
      [k, p[k] && typeof p[k] === "object" ? JSON.parse(JSON.stringify(p[k])) : p[k]]));
    for (const k of BASE_KEYS)
      p[k] = p._base[k] && typeof p._base[k] === "object"
        ? JSON.parse(JSON.stringify(p._base[k])) : p._base[k];
    p.wx = null; p.trend = null; p.inj_title = null; p.ov_note = null; p.prac = null;

    // the game: opponent and home/away from this week's kickoff table
    const g = kick[p.team];
    if (advanced) {
      p.opp = g ? g.opp : null;
      p.home = g ? g.home : null;
      p.wk_opp = g ? (g.home ? "vs " : "at ") + g.opp : "BYE";
      p.wk_ecr = p.wk_pos_rank = p.wk_grade = p.wk_proj = null;
    }

    // projection: Sleeper's current stat line
    const fresh = ov.proj[p.id];
    if (fresh && fresh.s) {
      p.pstats = fresh.s; p.pstats_src = "sleeper"; p.proj_src = "sleeper";
    } else if (okPos.has(p.pos) && g && p._base.pstats_src === "sleeper") {
      // Sleeper projected him before and projects nothing now
      p.pstats = {}; p.pstats_src = "sleeper"; p.proj_src = "sleeper";
      p.ov_note = "Sleeper now projects 0";
    }
    // no game this week (bye): nothing to project — only when the overlay's
    // kickoff table is plainly complete, so a short table can't zero a league
    if (!g && kickComplete && p.team && p.team !== "FA" && p.pos !== "DST") {
      if (p.pstats) p.pstats = {};
      p.opp = null;
    }

    // defenses: price off the current line
    if (p.pos === "DST" && p.dst_ctx && g && kick[g.opp] && kick[g.opp].implied != null)
      p.dst_ctx = Object.assign({}, p.dst_ctx, { opp_implied: kick[g.opp].implied });

    // weather
    const w = (ov.weather || {})[p.team];
    if (w && g && !g.final) {
      p.wx = w;
      if (w.mult && p.pos !== "DST" && p.pstats) p.pstats = weatherLine(p.pstats, w.mult);
    }
    if (p.pstats && p.pos !== "DST") p.proj = pprOf(p.pstats);

    // injury designation and practice participation
    const st = (ov.status || {})[p.id];
    p.inj = null; p.inj_note = null; p.inj_week = wk;
    if (st) {
      const des = st.injury_status || st.report_status || null;
      const outish = /^(IR|PUP|Sus|NFI|DNR|Out)$/i.test(des || "");
      p.inj = des ? (outish ? "Out" : des) : null;
      const bits = [];
      if (des && outish && !/^Out$/i.test(des)) bits.push(des);
      if (st.injury_body_part || st.practice_injury) bits.push(st.injury_body_part || st.practice_injury);
      const pr = st.practice === "DNP" ? "DNP" : st.practice === "Limited" ? "LP"
        : st.practice === "Full" ? "FP" : null;
      if (pr && des) bits.push(pr);
      p.inj_note = bits.join(" · ") || null;
      // practised short with no game designation yet (mid-week): flag the
      // practice itself rather than inventing a designation
      if (!des && (pr === "DNP" || pr === "LP")) p.prac = pr;
      const t = [];
      if (st.report_status) t.push(`Official report: ${st.report_status}`);
      if (st.practice) t.push(`Practice: ${st.practice}`);
      if (st.injury_notes) t.push(st.injury_notes);
      if (st.news_updated) t.push(`news ${new Date(st.news_updated).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}`);
      p.inj_title = t.join(" — ") || null;
    }

    // expert consensus, and how far it has moved this week
    const e = ex[p.id] || ex[`nm:${p.key}|${p.pos}`];
    if (e) {
      p.wk_ecr = e.ecr; p.wk_pos_rank = e.pos_rank; p.wk_grade = e.grade;
      if (e.proj != null) p.wk_proj = e.proj;
      if (e.ecr != null && e.ecr_first != null) {
        const move = Math.round((e.ecr_first - e.ecr) * 10) / 10;
        if (Math.abs(move) >= 2) p.trend = move;      // positive = rising
      }
    }
  }
  S.byId = new Map(S.players.map(p => [p.id, p]));
  S.ov = ov; S.ovAt = Date.parse(ov.generated_at); S.ovErr = null;
  return true;
}

/* ------------------------------------------------------------ weekly stat lines
   stats.json (same branch) carries every completed week's real stat lines from
   Sleeper, plus finished games of the week in progress. It is fetched only when
   overlay.stats_stamp changes. Applying it REPLACES the season fields built
   into the page (games, per-week lines, totals, shares, expected points), so
   the page is never stuck on the week its data was built. A player the file
   doesn't mention keeps the page's own numbers. */
const STATS_URL = OVERLAY_URL.replace(/overlay\.json$/, "stats.json");
const _ppr = l => scoreLine(l, DEFAULT_SCORING) || 0;

function applyStats(st) {
  if (!st || !st.weeks || Number(st.season) !== Number(S.meta.season)) return false;
  const weeks = Object.keys(st.weeks).map(Number).sort((a, b) => a - b);
  const rates = (S.meta.poe && S.meta.poe.rates) || {};
  let hit = 0;
  for (const p of S.players) {
    if (p.pos === "DST") continue;
    const sid = String(p.sleeper || p.id);
    const wk = [], lines = [];
    for (const w of weeks) {
      const l = st.weeks[String(w)][sid];
      if (l) { wk.push(w); lines.push(l); }
    }
    if (!lines.length) continue;
    hit++;
    const sum = {};
    for (const l of lines) for (const k in l) sum[k] = (sum[k] || 0) + l[k];
    const pooled = {};
    for (const k in sum) if (k[0] !== "_") pooled[k] = Math.round(sum[k] * 100) / 100;
    p._statsFresh = true;
    p.wstats = lines; p.logw = wk; p.logs = lines.map(l => Math.round(_ppr(l) * 100) / 100);
    p.g = lines.length; p.sstats = pooled;
    p.pts = Math.round(_ppr(pooled) * 100) / 100; p.ppg = Math.round(p.pts / p.g * 100) / 100;
    const n = k => sum[k] || 0;
    p.tgt = n("rec_tgt"); p.rec = n("rec"); p.recyd = n("rec_yd"); p.rectd = n("rec_td");
    p.car = n("rush_att"); p.ruyd = n("rush_yd"); p.rutd = n("rush_td");
    p.payd = n("pass_yd"); p.patd = n("pass_td"); p.int = n("pass_int"); p.att = n("pass_att");
    // shares, in percent, pooled over the games he played
    const lastSnap = [...lines].reverse().find(l => l._tsnp);
    p.snap_last = lastSnap ? Math.round(1000 * (lastSnap._snp || 0) / lastSnap._tsnp) / 10 : null;
    p.snap = n("_tsnp") ? Math.round(1000 * n("_snp") / n("_tsnp")) / 10 : null;
    p.tgt_share = n("_tt") ? Math.round(1000 * n("rec_tgt") / n("_tt")) / 10 : null;
    p.wopr = n("_tt") && n("_tay")
      ? Math.round((1.5 * n("rec_tgt") / n("_tt") + 0.7 * n("rec_air_yd") / n("_tay")) * 100) / 100
      : (n("_tt") ? Math.round(1.5 * n("rec_tgt") / n("_tt") * 100) / 100 : null);
    // expected points from the same opportunity prices the build used
    const r = rates[p.pos];
    if (r && p.pos !== "K") {
      const xfp = p.car * r.per_carry + p.tgt * r.per_target + p.att * r.per_attempt;
      p.xfp = Math.round(xfp * 100) / 100;
      p.x_rec = Math.round(p.tgt * r.catch_rate * 100) / 100;
      p.poe = Math.round((p.pts - xfp) * 100) / 100;
      p.poe_g = Math.round((p.pts - xfp) / p.g * 100) / 100;
      p.opps = Math.round(p.car + p.tgt + p.att);
    }
  }
  if (!hit) return false;
  if (Number(st.through_week) > Number(S.meta.completed_week || 0))
    S.meta.completed_week = Number(st.through_week);
  if (S.meta.sources) S.meta.sources.stats_through_week = S.meta.completed_week;
  if (typeof _replCache !== "undefined") _replCache = null;
  S.statsStamp = st.generated_at; S.statsHit = hit;
  return true;
}

async function loadStats(stamp) {
  if (!stamp || stamp === S.statsStamp) return false;
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 12000);
  try {
    const r = await fetch(`${STATS_URL}?s=${encodeURIComponent(stamp)}`,
      { cache: "no-store", signal: ctl.signal });
    if (!r.ok) return false;
    return applyStats(await r.json());
  } catch { return false; } finally { clearTimeout(t); }
}

async function fetchOverlay() {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), OVERLAY_TIMEOUT_MS);
  try {
    // the minute stamp stops a browser cache from pinning an old copy
    const r = await fetch(`${OVERLAY_URL}?m=${Math.floor(Date.now() / 60e3)}`,
      { cache: "no-store", signal: ctl.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(t); }
}

/** Fetch and apply; re-render if anything changed. Safe to call any time. */
async function loadOverlay(opts = {}) {
  if (_ovInFlight) return false;
  _ovInFlight = true;
  try {
    const ov = await fetchOverlay();
    if (!ov || (S.ov && ov.generated_at === S.ov.generated_at && !opts.force)) return false;
    const weekBefore = S.meta.upcoming_week;
    if (!applyOverlay(ov)) return false;
    await loadStats(ov.stats_stamp);
    if (opts.render !== false) {
      if (S.meta.upcoming_week !== weekBefore) renderTabs();
      if (S.tab) show(S.tab);
    }
    return true;
  } catch (err) {
    S.ovErr = String((err && err.message) || err);
    return false;
  } finally { _ovInFlight = false; }
}

function startOverlayTimer() {
  if (_ovTimer) return;
  _ovTimer = setInterval(() => { if (!document.hidden) loadOverlay(); }, OVERLAY_EVERY_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && (!S.ovAt || Date.now() - S.ovAt > OVERLAY_EVERY_MS)) loadOverlay();
  });
}

function overlayStatusHTML() {
  if (!S.ov) return S.ovErr
    ? `<div class="sub" style="margin-bottom:10px">Couldn't fetch the latest projections and injury news (${esc(S.ovErr)}). Showing the data built into this page.</div>`
    : "";
  const mins = Math.max(0, Math.round((Date.now() - S.ovAt) / 60e3));
  const age = mins < 1 ? "just now" : mins < 60 ? `${mins} min ago`
    : `${Math.round(mins / 6) / 10} h ago`;
  return `<div class="sub" style="margin-bottom:10px">Projections, injuries, weather and
    expert ranks updated ${age} · checks every ${S.ov.cadence ? S.ov.cadence.interval_min : 15} min${
    S.statsStamp ? ` · player stats through Week ${S.meta.completed_week}` : ""}</div>`;
}

function wxChip(p) {
  const w = p.wx;
  if (!w) return "";
  if (w.roof === "dome") return "";
  const bits = [];
  if (w.wind_mph != null) bits.push(`${Math.round(w.wind_mph)} mph`);
  if (w.temp_f != null) bits.push(`${Math.round(w.temp_f)}°`);
  // a retractable roof is usually closed in bad weather: no chip, and no adjustment
  if (w.roof !== "outdoor") return "";
  const flags = (w.flags || []).filter(f => f === "rain" || f === "snow");
  const m = w.mult || {};
  const pct = Math.round((1 - (p.pos === "K" ? (m.fg ?? 1) : (m.yd ?? 1))) * 100);
  const adj = pct >= 5;
  if (!adj && !flags.length) return "";
  const title = `${w.stadium || ""} forecast for kickoff: ${bits.join(", ")}${
    w.gust_mph ? `, gusts ${Math.round(w.gust_mph)} mph` : ""}${
    w.precip_prob ? `, ${w.precip_prob}% chance of precipitation` : ""}${
    pct > 0 ? ` — ${p.pos === "K" ? "field goals" : "passing and receiving yards"} −${pct}% in this projection` : ""}`;
  const label = flags.includes("snow") ? "snow" : flags.includes("rain") ? "rain"
    : `${Math.round(w.wind_mph || 0)} mph`;
  return `<span class="chip ${adj && pct >= 8 ? "warn" : ""}" title="${esc(title)}">🌬 ${esc(label)}</span>`;
}

function pracChip(p) {
  if (!p.prac) return "";
  return `<span class="chip ${p.prac === "DNP" ? "bad" : "warn"}" title="${esc(p.inj_title ||
    "Practice report")}">${p.prac === "DNP" ? "DNP" : "Limited"}</span>`;
}

function trendChip(p) {
  if (!p.trend) return "";
  const up = p.trend > 0;
  return `<span class="chip ${up ? "good" : "bad"}" title="FantasyPros consensus rank has moved ${
    Math.abs(p.trend)} spots ${up ? "up" : "down"} since the first read this week">${up ? "▲" : "▼"}${Math.abs(Math.round(p.trend))}</span>`;
}
