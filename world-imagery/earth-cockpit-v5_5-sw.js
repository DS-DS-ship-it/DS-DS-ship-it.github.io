const VERSION = "earth-cockpit-v5_5-1";
const SHELL_CACHE = `${VERSION}-shell`;

const SHELL_ASSETS = [
  "./earth-cockpit-v5_5.html",
  "./earth-cockpit-v5_5-sw.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await cache.addAll(SHELL_ASSETS);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => { if (!k.startsWith(VERSION)) return caches.delete(k); }));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin === self.location.origin) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(event.request);
      if (cached) return cached;
      const res = await fetch(event.request);
      if (event.request.method === "GET" && res.ok) cache.put(event.request, res.clone());
      return res;
    })());
  }
});
