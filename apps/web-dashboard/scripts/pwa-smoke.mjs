/**
 * Exercise the install/update state machine with stubbed browser APIs.
 *
 * There is no headless browser in this project, so the shipped module is evaluated in
 * Node instead: same file the browser loads, with `beforeinstallprompt`, a waiting
 * service worker and `navigator.storage` faked. Any deviation exits non-zero.
 *
 *   node scripts/pwa-smoke.mjs        (run by tests/test_pwa.py when node is present)
 */
import assert from 'node:assert/strict'

const mem = new Map()
const listeners = {}
const messages = []
let reloads = 0
let updateCalls = 0

globalThis.localStorage = {
  getItem: (k) => (mem.has(k) ? mem.get(k) : null),
  setItem: (k, v) => mem.set(k, String(v)),
  removeItem: (k) => mem.delete(k),
}

const registration = {
  waiting: { postMessage: (m) => messages.push(m) },
  addEventListener: (k, f) => { listeners[`reg:${k}`] = f },
  update: async () => { updateCalls += 1 },
}

globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  addEventListener: (k, f) => { listeners[k] = f },
  location: { reload: () => { reloads += 1 } },
}

Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
    userAgent: 'Mozilla/5.0 (Linux; Android 14)',
    maxTouchPoints: 5,
    serviceWorker: { register: async () => registration, addEventListener: () => {} },
    storage: {
      persist: async () => true,
      estimate: async () => ({ usage: 3.5 * 1024 * 1024, quota: 512 * 1024 * 1024 }),
    },
  },
})

const pwa = await import('../src/lib/pwa.js')

// --- a fresh module, nothing installable yet
assert.equal(pwa.pwa.canInstall, false)
assert.equal(pwa.pwa.installed, false)
assert.equal(pwa.pwa.dismissed, false)

// --- the browser offers an install prompt: we show our own button, not its mini-infobar
pwa.listenForInstall()
let prevented = false
listeners['beforeinstallprompt']({
  preventDefault() { prevented = true },
  prompt() {},
  userChoice: Promise.resolve({ outcome: 'accepted' }),
})
assert.equal(prevented, true, 'the default browser banner must be suppressed')
assert.equal(pwa.pwa.canInstall, true)

assert.equal(await pwa.promptInstall(), true)
assert.equal(pwa.pwa.installed, true)
assert.equal(pwa.pwa.canInstall, false, 'the invitation must not be offered twice')
assert.equal(await pwa.promptInstall(), false, 'no deferred prompt left')

// --- a new build is waiting: surface it, do not apply it behind the user's back
const reg = await pwa.registerWorker()
assert.ok(reg)
assert.equal(pwa.pwa.updateReady, true)
assert.equal(reloads, 0, 'registering must not reload the page')

// --- storage: ask the browser to keep the shell cache, report the size
assert.equal(pwa.pwa.storagePersisted, true)
assert.equal(pwa.pwa.storageUsedMb, 3.5)
assert.equal(pwa.pwa.storageQuotaMb, 512)

// --- update polling is a real timer that can be stopped
const stop = pwa.watchForUpdates(20)
await new Promise((r) => setTimeout(r, 60))
stop()
assert.ok(updateCalls >= 1, 'watchForUpdates must poll registration.update()')
const seen = updateCalls
assert.ok(seen >= 1)

// --- applying the update tells the worker to activate, then reloads once
pwa.pwa.updateReady = true
await pwa.applyUpdate()
await new Promise((r) => setTimeout(r, 1600))
assert.deepEqual(messages, [{ type: 'SKIP_WAITING' }])
assert.equal(reloads, 1)

// --- dismissing is remembered across reloads
pwa.dismissInstall()
assert.equal(pwa.pwa.dismissed, true)
assert.equal(localStorage.getItem('no7.pwa.dismissed'), '1')

console.log('pwa smoke: install, update, storage and dismissal all behave')
