/* ==============================================================================
   AI Campus Placement Agent - Service Worker (#471)
   Provides PWA installability, static asset caching, and offline fallback.
   CRITICAL PRIVACY RULE: Never caches personal pages (dashboard, reports,
   interview, profile, notes) or dynamic API responses.
   ============================================================================== */

const CACHE_NAME_STATIC = 'ai-campus-static-v1';
const CACHE_NAME_OFFLINE = 'ai-campus-offline-v1';
const OFFLINE_URL = '/offline';

const PRECACHE_ASSETS = [
  OFFLINE_URL,
  '/manifest.json',
  '/static/css/style.css',
  '/static/css/print.css',
  '/static/js/script.js',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/icons/icon-maskable-192x192.png',
  '/static/icons/icon-maskable-512x512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/icon.svg'
];

// Routes containing personal student data or dynamic private evaluation state
const PERSONAL_ROUTES = [
  '/dashboard',
  '/interview',
  '/download',
  '/profile',
  '/notes',
  '/history',
  '/applications',
  '/saved-',
  '/role-preparation',
  '/leaderboard',
  '/certificate',
  '/account',
  '/streak',
  '/login',
  '/logout',
  '/register',
  '/my-reports'
];

/**
 * Checks if a URL points to personal data or an API endpoint.
 * @param {URL} url 
 * @returns {boolean}
 */
function isPersonalOrApiUrl(url) {
  const path = url.pathname.toLowerCase();
  if (path.startsWith('/api/')) {
    return true;
  }
  return PERSONAL_ROUTES.some(route => path.startsWith(route));
}

// Service Worker Installation: Cache critical static assets and offline template
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME_STATIC).then(cache => {
      return cache.addAll(PRECACHE_ASSETS).catch(err => {
        console.warn('Pre-caching non-fatal asset failure:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Service Worker Activation: Clean up stale caches and claim clients immediately
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME_STATIC && cacheName !== CACHE_NAME_OFFLINE) {
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Request Handler
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  // 1. Only handle GET requests; pass non-GET requests directly to network
  if (request.method !== 'GET') {
    return;
  }

  // 2. API Requests: Always Network-Only; NEVER cache API responses
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(
          JSON.stringify({
            status: 'error',
            offline: true,
            error: 'offline',
            message: 'You are currently offline. Please reconnect to internet to fetch or update data.'
          }),
          {
            status: 503,
            statusText: 'Service Unavailable',
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // 3. Navigation Requests (HTML document loading)
  if (request.mode === 'navigate' || (request.headers.get('accept') && request.headers.get('accept').includes('text/html'))) {
    event.respondWith(
      fetch(request)
        .then(networkResponse => {
          // If network succeeded, return response directly.
          // NEVER cache personal data pages!
          return networkResponse;
        })
        .catch(() => {
          // Network failed (offline): serve the friendly offline page
          return caches.match(OFFLINE_URL).then(cachedOffline => {
            return cachedOffline || caches.match('/offline');
          });
        })
    );
    return;
  }

  // 4. Personal pages (if requested via non-navigate fetch): Network-Only, NEVER cache
  if (isPersonalOrApiUrl(url)) {
    event.respondWith(
      fetch(request).catch(() => {
        return caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  // 5. Static Assets (CSS, JS, Fonts, Images, Icons, Manifest): Stale-While-Revalidate
  if (
    url.pathname.startsWith('/static/') ||
    url.pathname === '/manifest.json' ||
    url.hostname.includes('cdn.jsdelivr.net') ||
    url.hostname.includes('cdnjs.cloudflare.com')
  ) {
    event.respondWith(
      caches.match(request).then(cachedResponse => {
        const fetchPromise = fetch(request).then(networkResponse => {
          if (networkResponse && networkResponse.status === 200) {
            const responseToCache = networkResponse.clone();
            caches.open(CACHE_NAME_STATIC).then(cache => {
              cache.put(request, responseToCache);
            });
          }
          return networkResponse;
        }).catch(() => cachedResponse);

        return cachedResponse || fetchPromise;
      })
    );
    return;
  }

  // Fallback: standard network fetch
  event.respondWith(fetch(request));
});
