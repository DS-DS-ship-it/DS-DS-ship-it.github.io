// Earth Cockpit SW (best-effort caching for GitHub Pages)
const VERSION = 'earth-cockpit-v2.0.1';
const APP_CACHE = `${VERSION}-app`;
const RUNTIME_CACHE = `${VERSION}-runtime`;

const APP_SHELL = [
  './',
  './index.html',
  './sw.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    await cache.addAll(APP_SHELL);
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(k => {
      if (!k.startsWith(VERSION)) return caches.delete(k);
    }));
    self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== 'GET') return;

  event.respondWith((async () => {
    // Same-origin: cache-first
    if (url.origin === location.origin) {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(APP_CACHE);
        cache.put(req, fresh.clone());
        return fresh;
      } catch (e) {
        const fallback = await caches.match('./index.html');
        if (fallback) return fallback;
        throw e;
      }
    }

    // Cross-origin runtime: stale-while-revalidate
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match(req);

    const fetchPromise = fetch(req).then((fresh) => {
      cache.put(req, fresh.clone()).catch(() => {});
      return fresh;
    }).catch(() => cached);

    return cached || fetchPromise;
  })());
});
