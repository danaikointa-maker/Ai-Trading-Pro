import assert from 'node:assert/strict'
import { createServer } from 'vite'

// Real store via Vite, without listening on a port or contacting the API.
globalThis.localStorage = { getItem: () => null }
globalThis.window = new EventTarget()
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
try {
  const store = await server.ssrLoadModule('/src/lib/store.js')
  const forecast = { symbol: 'XAUUSD', model_version: 'v1', model_approved: true }
  const initial = () => {
    store.state.live = null
    store.applyLive({ symbol: 'XAUUSD', forecast, model: { version: 'v1', approved: true } })
  }
  for (const [name, frame] of [
    ['explicit-null', { forecast: null }],
    ['revoke-light', { type: 'tick', model: { version: 'v1', approved: false } }],
    ['version-light', { type: 'tick', model: { version: 'v2', approved: true } }],
    ['symbol-light', { type: 'tick', symbol: 'EURUSD' }],
  ]) {
    initial()
    store.applyLive(frame)
    assert.equal(store.state.live.forecast, null, name)
  }
  initial()
  store.applyLive({ type: 'tick', ticker: { last: 2000 } })
  assert.equal(store.state.live.forecast.model_version, 'v1', 'same-authority light frames preserve forecast')
  store.applyLive({ forecast: { ...forecast, model_approved: false }, model: { version: 'v1', approved: false } })
  store.applyLive({ type: 'tick' })
  assert.equal(store.state.live.forecast.model_approved, false, 'baseline remains visible')
  console.log('forecast cache: null, revocation, version and symbol changes are enforced')
} finally {
  await server.close()
}