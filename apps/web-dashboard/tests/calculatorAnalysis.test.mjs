import assert from 'node:assert/strict'
import test from 'node:test'

import { projectAtrVolatility, projectSupportResistance } from '../src/lib/calculatorAnalysis.js'

function snapshot(overrides = {}) {
  return {
    snapshot: {
      symbol: 'XAUUSD', timeframe: 'M5', server_time: 1_760_000_000, price: 2000,
      spec: { source: 'broker', digits: 2 },
      indicators: { atr14: 10, atr_points: 1000, atr14_valid: true },
      regime: { regime: 'trend', adx: 25, atr_percentile: 0.6 },
      data_quality: { ok: true, feed: 'mt5-live', staleness_seconds: 1.2 },
      ...overrides,
    },
    supports: [
      { id: 'far', low: 1900, mid: 1905, high: 1910, quality: 'medium', status: 'candidate', strength: 0.4, distance_atr: 9 },
      { id: 'near', low: 1980, mid: 1985, high: 1990, quality: 'high', status: 'confirmed', strength: 0.9, distance_atr: 1 },
      { id: 'bad', low: 1990, mid: 1980, high: 2000, quality: 'high', status: 'confirmed', strength: 1, distance_atr: 0 },
    ],
    resistances: [],
  }
}

test('ATR projection requires fresh data and an explicitly valid closed-bar ATR', () => {
  const result = projectAtrVolatility(snapshot())
  assert.equal(result.status, 'ready')
  assert.equal(result.atr_percent, 0.5)
  assert.equal(result.timeframe, 'M5')
  assert.equal(result.closed_bar_close_utc, new Date((1_760_000_000 + 300) * 1000).toISOString())
  assert.equal(projectAtrVolatility(snapshot({ indicators: { atr14: 2, atr_points: 200 } })).status, 'unavailable')
  assert.equal(projectAtrVolatility(snapshot({ data_quality: { ok: false, reason: 'stale' } })).status, 'unavailable')
})

test('support and resistance projection keeps nearest levels and quality labels', () => {
  const result = projectSupportResistance(snapshot())
  assert.equal(result.status, 'ready')
  assert.deepEqual(result.supports.map((zone) => zone.id), ['near', 'far'])
  assert.equal(result.supports[0].status, 'confirmed')
  assert.equal(result.supports[0].quality, 'high')
  const stale = projectSupportResistance(snapshot({ data_quality: { ok: false, reason: 'stale' } }))
  assert.equal(stale.status, 'unavailable')
  assert.equal(stale.supports, undefined)
})
