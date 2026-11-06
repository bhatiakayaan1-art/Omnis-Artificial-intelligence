const CACHE = "omnis-shell-v12";
const BASE_URL = new URL(self.registration.scope);
const APP_SHELL = ["", "index.html", "manifest.json", "icon.svg", "icon-180.png", "icon-192.png", "icon-512.png"]
  .map(path => new URL(path, BASE_URL).pathname);

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE).map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return;
  }
  if (request.mode === "navigate") {
    const indexPath = new URL("index.html", BASE_URL).pathname;
    event.respondWith(fetch(request).catch(() => caches.match(indexPath)));
    return;
  }
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok && url.pathname === BASE_URL.pathname) {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(request, copy));
      }
      return response;
    }))
  );
});
