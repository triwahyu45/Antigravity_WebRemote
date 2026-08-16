const CACHE_NAME = 'wahyuai-v2';
const STATIC_ASSETS = [
  '/',
  '/wahyuai',
  '/css/app.css',
  '/js/app.js'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS).catch(() => {}))
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (event.request.url.includes('/api/') || event.request.url.includes('/ws/')) {
    return; // Pass through live dynamic API and WS
  }
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
