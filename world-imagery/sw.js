/* sw.js — Earth Cockpit shell cache (best-effort) */
const CACHE_NAME = "earth-cockpit-shell-v1";
const ASSETS = [
  "./",
  "./index.html",
  "./sw.js"
];

// Install: cache the shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.map(k => (k === CACHE_NAME ? null : caches.delete(k)))))
      .then(() => self.clients.claim())
  );
});

// Fetch: cache-first for same-origin shell; network-first otherwise.
// Note: cross-origin tiles are often "opaque" and may or may not be cacheable depending on browser rules.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only guarantee caching for our own origin + our shell
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(req).then((cached) => {
        return cached || fetch(req).then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(()=>{});
          return resp;
        });
      })
    );
    return;
  }

  // For cross-origin: try network, fallback to cache (best-effort)
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
