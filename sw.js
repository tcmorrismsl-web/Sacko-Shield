/* Retired. The offline-copy worker that used to live here could leave the
   app on a blank screen in Safari (it extended the request's lifetime after
   an await, which WebKit rejects, so the page request failed outright).
   This version has no fetch handler: once it takes over it deletes the stored
   copy, unregisters itself and reloads any open page from the network.
   Keep this file published so phones that installed the old worker get it. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil((async () => {
  try { for (const k of await caches.keys()) await caches.delete(k); } catch {}
  try { await self.registration.unregister(); } catch {}
  try {
    const open = await self.clients.matchAll({ type: "window" });
    for (const c of open) { try { await c.navigate(c.url); } catch {} }
  } catch {}
})()));
