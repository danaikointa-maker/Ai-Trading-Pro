/* No7 AI Trading Pro — service worker (production only).
 *
 * The shell (index.html + its hashed assets + icons) is cached so the app opens
 * without a network. Nothing from /api/ or /ws is ever cached: prices and orders must
 * come from the server, never from a stale copy — showing an old price as if it were
 * live is worse than showing an offline banner.
 *
 * __NO7_VERSION__ is replaced by the server with a hash of the built index.html, so a
 * new build is a new cache and old caches are dropped on activate.
 */
const VERSION = '__NO7_VERSION__'
const CACHE = `no7-shell-${VERSION}`
const CORE = ['/', '/offline.html', '/manifest.webmanifest',
              '/icon-192.png', '/icon-512.png', '/icon-maskable-512.png', '/apple-touch-icon.png']

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE)
    await cache.addAll(CORE).catch(() => {})
    // Precache the exact bundle index.html points at, by reading it rather than by
    // guessing filenames (they are content-hashed on every build).
    try {
      const page = await fetch('/index.html', { cache: 'reload' })
      if (page.ok) {
        const html = await page.clone().text()
        await cache.put('/index.html', page)
        const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1])
        await Promise.all([...new Set(assets)].map((url) =>
          fetch(url).then((res) => (res.ok ? cache.put(url, res) : null)).catch(() => null)))
      }
    } catch { /* offline during install: CORE alone still boots the offline page */ }
    await self.skipWaiting()
  })())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys()
    await Promise.all(names.filter((n) => n.startsWith('no7-shell-') && n !== CACHE)
      .map((n) => caches.delete(n)))
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return  // live only

  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(request)
        const cache = await caches.open(CACHE)
        if (fresh.ok && url.pathname === '/') cache.put('/', fresh.clone())
        return fresh
      } catch {
        const cache = await caches.open(CACHE)
        return (await cache.match('/')) || (await cache.match('/offline.html'))
          || new Response('offline', { status: 503, headers: { 'Content-Type': 'text/plain' } })
      }
    })())
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE)
      const hit = await cache.match(request)
      if (hit) return hit
      const fresh = await fetch(request)
      if (fresh.ok) (await caches.open(CACHE)).put(request, fresh.clone())
      return fresh
    })())
  }
})
