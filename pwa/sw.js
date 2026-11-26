// Offline fallback for the home-screen app. Everything is network-first, so an open with signal always
// shows the newest page and data; the cache only answers when the network does not. The CDN scripts are
// pinned to exact versions, so those are served from the cache first.
const CACHE = 'ledger-v1';
const DATA = ['daily', 'tasks', 'prices', 'waveform', 'meta', 'insights'].map((n) => 'data/' + n + '.json');
const PRECACHE = [
  './', 'app.js', 'manifest.webmanifest', 'icon.svg', 'apple-touch-icon.png', ...DATA,
  'https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js',
  'https://cdn.jsdelivr.net/npm/echarts@6.1.0/dist/echarts.min.js',
];
const PINNED = new Set(['cdn.jsdelivr.net', 'fonts.gstatic.com']);
const RUNTIME = new Set([location.hostname, 'fonts.googleapis.com']);

self.addEventListener('install', (e) => {
  // One file failing (say, a CDN hiccup) should not stop the rest from being cached.
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => {})))));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

const keep = (e, req, res) => {
  if (res.ok || res.type === 'opaque') {
    const copy = res.clone();
    e.waitUntil(caches.open(CACHE).then((c) => c.put(req, copy)));
  }
  return res;
};

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const host = new URL(req.url).hostname;
  if (PINNED.has(host)) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => keep(e, req, res))));
  } else if (RUNTIME.has(host)) {
    e.respondWith(fetch(req).then((res) => keep(e, req, res))
      .catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || Response.error())));
  }
});
