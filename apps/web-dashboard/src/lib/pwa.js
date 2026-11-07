/**
 * Install / update / storage state for the PWA.
 *
 * Everything here is about *the app shell being trustworthy*: it must be installable,
 * say when a new build is ready instead of silently swapping assets mid-session, and
 * never imply an offline copy of data is live. Data itself stays out of this file.
 */
import { reactive } from 'vue'

const STORE_KEY = 'no7.pwa.dismissed'
// Guarded so the module can also be evaluated outside a browser (tests, SSR-ish tooling).
const store = typeof localStorage === 'undefined' ? null : localStorage

export const pwa = reactive({
  canInstall: false,        // the browser fired beforeinstallprompt
  installed: false,         // running from the home screen / installed window
  iosHint: false,           // Safari on iOS: no prompt API, only a manual hint
  dismissed: store?.getItem(STORE_KEY) === '1',
  updateReady: false,       // a new service worker is waiting
  storagePersisted: null,   // navigator.storage.persist() result (null = unknown)
  storageQuotaMb: null,
  storageUsedMb: null,
})

let deferredPrompt = null
let registration = null

export function isStandalone() {
  if (typeof window === 'undefined') return false
  const modes = ['standalone', 'minimal-ui', 'fullscreen', 'window-controls-overlay']
  return modes.some((m) => window.matchMedia(`(display-mode: ${m})`).matches)
    || window.navigator?.standalone === true   // iOS Safari, legacy flag
}

export function isIos() {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  const touch = navigator.maxTouchPoints > 0
  // iPadOS 13+ reports a desktop UA; the touch-point check catches it.
  return /iPad|iPhone|iPod/.test(ua) || (/Macintosh/.test(ua) && touch)
}

export function dismissInstall() {
  pwa.dismissed = true
  store?.setItem(STORE_KEY, '1')
}

/** Show the browser's install sheet. Returns true when the user accepted. */
export async function promptInstall() {
  if (!deferredPrompt) return false
  deferredPrompt.prompt()
  const { outcome } = await deferredPrompt.userChoice
  deferredPrompt = null
  pwa.canInstall = false
  if (outcome === 'accepted') {
    pwa.installed = true
    persistStorage()
  }
  return outcome === 'accepted'
}

/** Ask the browser not to evict our shell cache. Best effort — it can say no. */
export async function persistStorage() {
  if (!navigator.storage?.persist) return
  try {
    pwa.storagePersisted = await navigator.storage.persist()
  } catch {
    pwa.storagePersisted = false
  }
  await refreshStorageEstimate()
}

export async function refreshStorageEstimate() {
  if (!navigator.storage?.estimate) return
  try {
    const { usage = 0, quota = 0 } = await navigator.storage.estimate()
    pwa.storageUsedMb = Math.round((usage / 1024 / 1024) * 10) / 10
    pwa.storageQuotaMb = Math.round(quota / 1024 / 1024)
  } catch {
    /* estimate is optional */
  }
}

/** Activate the waiting worker; the page reloads once it takes over. */
export async function applyUpdate() {
  const waiting = registration?.waiting
  if (!waiting) {
    window.location.reload()
    return
  }
  waiting.postMessage({ type: 'SKIP_WAITING' })
  // controllerchange fires after the new worker claims this page; the timeout is a
  // fallback for browsers that swallow it rather than leaving the user on a dead button.
  setTimeout(() => window.location.reload(), 1500)
}

export function listenForInstall() {
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()          // keep our own button instead of Chrome's mini-infobar
    deferredPrompt = event
    pwa.canInstall = true
  })
  window.addEventListener('appinstalled', () => {
    pwa.installed = true
    pwa.canInstall = false
    deferredPrompt = null
    persistStorage()
  })
  pwa.installed = isStandalone()
  pwa.iosHint = !pwa.installed && isIos()
  window.matchMedia('(display-mode: standalone)')
    .addEventListener?.('change', (e) => { pwa.installed = e.matches })
}

/**
 * Register the worker and surface updates. `skipWaiting` is deliberately *not* called
 * by the worker on install: a new build taking over mid-session can leave the page
 * running yesterday's JS against today's hashed assets, so the user is asked instead.
 */
export async function registerWorker() {
  if (!('serviceWorker' in navigator)) return null
  try {
    registration = await navigator.serviceWorker.register('/sw.js')
  } catch (err) {
    console.warn('service worker not registered:', err)
    return null
  }
  if (registration.waiting) pwa.updateReady = true
  registration.addEventListener('updatefound', () => {
    const worker = registration.installing
    if (!worker) return
    worker.addEventListener('statechange', () => {
      // `controller` means an old worker is already serving this page → this is an update.
      if (worker.state === 'installed' && navigator.serviceWorker.controller) {
        pwa.updateReady = true
      }
    })
  })
  let reloading = false
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (reloading) return
    reloading = true
    window.location.reload()
  })
  persistStorage()
  return registration
}

/** Poll for a new build on a slow timer; SW updates otherwise only appear on navigation. */
export function watchForUpdates(intervalMs = 30 * 60 * 1000) {
  if (!registration) return () => {}
  const timer = setInterval(() => registration.update().catch(() => {}), intervalMs)
  return () => clearInterval(timer)
}
