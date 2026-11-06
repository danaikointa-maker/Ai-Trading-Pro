/* No7 AI Trading Pro — service worker
 *
 * Rules that matter for a trading dashboard:
 *  - never cache anything under /api or /ws. A stale price or a stale position
 *    list is worse than no data at all, so those always go to the network.
 *  - the app shell (HTML/JS/CSS/icons) is cached so the app still opens
 *    offline and can tell the user it is offline.
 *  - hashed build assets are immutable, so cache-first is safe for them.
 */

const VERSION = 'no7-v2'
const SHELL_CACHE = `${VERSION}-shell`
const ASSET_CACHE = `${VERSION}-assets`

const SHELL = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL).catch(() => undefined))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  )
})

const isLiveData = (url) =>
  url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (isLiveData(url)) return // always network: never serve a stale market

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(SHELL_CACHE).then((cache) => cache.put('/index.html', copy)).catch(() => {})
          return response
        })
        .catch(() => caches.match('/index.html').then((cached) => cached
          || new Response(
            '<!doctype html><meta charset="utf-8"><title>ออฟไลน์</title>'
            + '<body style="background:#07090c;color:#e8ecf3;font-family:ui-sans-serif;padding:32px">'
            + '<h1>ออฟไลน์</h1><p>เปิดแอปไม่ได้เพราะยังไม่เคยโหลดสำเร็จ — ต่ออินเทอร์เน็ตแล้วลองใหม่</p>',
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } },
          ))),
    )
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(ASSET_CACHE).then((cache) => cache.put(request, copy)).catch(() => {})
        }
        return response
      })),
    )
    return
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(ASSET_CACHE).then((cache) => cache.put(request, copy)).catch(() => {})
        }
        return response
      })
      .catch(() => caches.match(request)),
  )
})
