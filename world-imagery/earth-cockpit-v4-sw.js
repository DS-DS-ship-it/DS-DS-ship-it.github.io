/* Earth Cockpit v4 — Offline "shell" cache
   Note: Cross-origin tiles (Esri, NASA, CARTO, RainViewer) may be cached as opaque responses depending on browser policy.
   This SW guarantees the app UI loads offline; tiles may or may not.
*/
const CACHE = 'earth-cockpit-v4-shell-v1';
const SHELL = [
  './earth-cockpit-v4.html',
  './earth-cockpit-v4-sw.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL);
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => (k === CACHE ? null : caches.delete(k))));
    self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GET
  if (req.method !== 'GET') return;

  // Network-first for tiles/apis (freshness), cache fallback if available
  const isTileOrApi =
    url.hostname.includes('arcgisonline.com') ||
    url.hostname.includes('gibs.earthdata.nasa.gov') ||
    url.hostname.includes('cartocdn.com') ||
    url.hostname.includes('rainviewer.com') ||
    url.hostname.includes('open-meteo.com') ||
    url.hostname.includes('nominatim.openstreetmap.org');

  if (isTileOrApi) {
    event.respondWith((async () => {
      try {
        const net = await fetch(req);
        // Best-effort cache (may be opaque)
        const cache = await caches.open(CACHE);
        cache.put(req, net.clone()).catch(() => {});
        return net;
      } catch (e) {
        const cached = await caches.match(req);
        return cached || new Response('', { status: 504, statusText: 'Offline / fetch failed' });
      }
    })());
    return;
  }

  // Default: cache-first for shell
  event.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const net = await fetch(req);
      const cache = await caches.open(CACHE);
      cache.put(req, net.clone()).catch(() => {});
      return net;
    } catch (e) {
      return cached || new Response('Offline', { status: 200, headers: { 'Content-Type': 'text/plain' }});
    }
  })());
});
