/* earth-cockpit-v6-sw.js — lightweight cache (v6) */
const CACHE = "earth-cockpit-v6-cache-v1";

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll([
      "./earth-cockpit-v6.html",
      "./earth-cockpit-v6-sw.js"
    ]);
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => (k === CACHE ? null : caches.delete(k))));
    self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Cache-first for same-origin app files
  if (url.origin === location.origin) {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      cache.put(req, res.clone());
      return res;
    })());
    return;
  }

  // Network-first for cross-origin tiles/APIs; fallback to cache
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      return await fetch(req);
    } catch {
      const hit = await cache.match(req);
      return hit || Response.error();
    }
  })());
});
