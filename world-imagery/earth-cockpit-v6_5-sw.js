/* Earth Cockpit v6.5 — Service Worker (offline shell only) */
const VERSION = "earth-cockpit-v6_5-1";
const SHELL_CACHE = `${VERSION}-shell`;

const SHELL_ASSETS = [
  "./earth-cockpit-v6_5.html",
  "./earth-cockpit-v6_5-sw.js"
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
    await Promise.all(keys.map(k => {
      if (!k.startsWith(VERSION)) return caches.delete(k);
    }));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith((async () => {
    const cache = await caches.open(SHELL_CACHE);
    const hit = await cache.match(event.request);
    if (hit) return hit;

    const res = await fetch(event.request);
    if (event.request.method === "GET" && res.ok) cache.put(event.request, res.clone());
    return res;
  })());
});
