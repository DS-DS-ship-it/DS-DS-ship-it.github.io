/* earth-cockpit-v5-sw.js — minimal offline shell cache */
const VERSION = "earth-cockpit-v5-7-2-b573";
const CACHE = `${VERSION}-shell`;

const ASSETS = [
  "./earth-cockpit-v5_7_0.html",
  "./earth-cockpit-v5-sw.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(ASSETS);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => (k === CACHE) ? null : caches.delete(k)));
    await self.clients.claim();
  })());
});

// Same-origin only (don’t cache cross-origin map tiles)
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith((async () => {
    const c = await caches.open(CACHE);
    const cached = await c.match(event.request);
    if (cached) return cached;

    try {
      const res = await fetch(event.request);
      if (event.request.method === "GET" && res.ok) c.put(event.request, res.clone());
      return res;
    } catch (e) {
      if (event.request.mode === "navigate") {
        const shell = await c.match("./earth-cockpit-v5_7_0.html");
        if (shell) return shell;
      }
      throw e;
    }
  })());
});
