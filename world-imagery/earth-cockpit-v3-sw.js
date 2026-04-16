/* Earth Cockpit v3 SW — app-shell only (safe for GitHub Pages) */
const CACHE = "earth-cockpit-v3-shell";
const ASSETS = [
  "./earth-cockpit-v3.html",
  "./earth-cockpit-v3-sw.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => (k !== CACHE) ? caches.delete(k) : null)))
      .then(() => self.clients.claim())
  );
});

// Cache-first for SAME-ORIGIN only; do not cache cross-origin tiles/APIs.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(event.request).then(cached => cached || fetch(event.request).then(resp => {
      const copy = resp.clone();
      caches.open(CACHE).then(c => c.put(event.request, copy)).catch(() => {});
      return resp;
    }))
  );
});
