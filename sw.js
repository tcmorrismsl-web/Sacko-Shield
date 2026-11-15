/* Sacko Shield offline copy.
   The page is one ~1.4 MB file. On a weak signal (a stadium, a car) the
   phone could sit on a blank screen while it downloads, so this worker keeps
   the last copy and opens it instantly, then refreshes the stored copy in the
   background for next time. It only handles the page itself: data, scores
   and everything else go straight to the network as before. */
const CACHE = "sacko-page-v1";
const PAGE = new URL("./", self.location).href;

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => fetch(PAGE, { cache: "no-store" }).then(r => r.ok ? c.put(PAGE, r) : null))
    .catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function refresh() {
  const r = await fetch(PAGE, { cache: "no-store" });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const c = await caches.open(CACHE);
  await c.put(PAGE, r.clone());
  return r;
}

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.mode !== "navigate") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.href.split(/[?#]/)[0] !== PAGE) return;
  e.respondWith((async () => {
    const hit = await caches.match(PAGE);
    if (hit) {
      e.waitUntil(refresh().catch(() => {}));
      return hit;
    }
    try { return await refresh(); }
    catch { return fetch(req); }
  })());
});

self.addEventListener("message", e => {
  if (!e.data || e.data.type !== "update") return;
  const port = e.ports && e.ports[0];
  e.waitUntil(refresh()
    .then(() => port && port.postMessage({ ok: true }))
    .catch(() => port && port.postMessage({ ok: false })));
});
