/* Earth Cockpit v6.7 — service worker (optional offline shell)
   - Caches only the app shell
   - Does NOT cache cross-origin tiles/scripts aggressively
   - IMPORTANT: v6.7 HTML disables SW by default (ENABLE_SW=false).
*/
const VERSION = "earth-cockpit-v6-7";
const SHELL_CACHE = `${VERSION}-shell`;

const SHELL_ASSETS = [
  "./earth-cockpit-v6_7.html",
  "./earth-cockpit-v6_7-sw.js"
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

  // Only handle same-origin for offline shell
  if (url.origin === self.location.origin) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(event.request);
      if (cached) return cached;
      try {
        const res = await fetch(event.request);
        if (event.request.method === "GET" && res.ok) {
          cache.put(event.request, res.clone());
        }
        return res;
      } catch (e) {
        if (event.request.mode === "navigate") {
          const shell = await cache.match("./earth-cockpit-v6_7.html");
          if (shell) return shell;
        }
        throw e;
      }
    })());
    return;
  }

  // Cross-origin: pass-through (no cache)
});
