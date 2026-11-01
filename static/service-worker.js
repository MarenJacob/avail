const CACHE_NAME = "jennys-kitchen-shell-v2";
const CORE = ["/", "/menu", "/static/css/style.css", "/static/manifest.webmanifest", "/static/images/jennys-kitchen-logo.png", "/static/icon-192.png", "/static/icon-512.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  event.respondWith(fetch(request).then(response => {
    if (response.ok && (request.destination === "style" || request.destination === "script" || request.destination === "image")) {
      const copy = response.clone(); caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
    }
    return response;
  }).catch(async () => {
    const cached = await caches.match(request);
    if (cached) return cached;
    if (request.mode === "navigate") return caches.match("/menu");
    return new Response("You are offline. Reconnect and try again.", {status: 503, headers: {"Content-Type": "text/plain"}});
  }));
});