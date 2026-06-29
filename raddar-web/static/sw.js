// Raddar service worker — installable PWA + offline-ish first paint.
// Strategy: cache-first for static assets; network-first for the live API and pages so
// event data never goes stale, falling back to the last cached map only when offline.
const CACHE = "raddar-v11";
const STATIC_ASSETS = [
  "/static/css/styles.css",
  "/static/js/map.js",
  "/static/js/pins.js",
  "/static/js/urgency.js",
  "/static/js/host.js",
  "/static/js/bookmark.js",
  "/static/icon.svg",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // Static assets: cache-first.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request)));
    return;
  }

  // Map page + API: network-first, fall back to cache when offline.
  if (url.pathname === "/" || url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(request, copy));
          return resp;
        })
        .catch(() => caches.match(request))
    );
  }
});
