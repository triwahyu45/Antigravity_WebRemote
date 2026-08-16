const CACHE_NAME = "local-ai-agent-v1";
const ASSETS = [
    "/",
    "/css/app.css",
    "/js/app.js",
    "/manifest.json"
];

self.addEventListener("install", (e) => {
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
    );
});

self.addEventListener("fetch", (e) => {
    // Network first, fallback to cache
    e.respondWith(
        fetch(e.request).catch(() => caches.match(e.request))
    );
});
