import test from 'node:test'
import assert from 'node:assert/strict'

import {
  clampBarSpacing,
  latestLogicalRange,
  matchesChartSymbol,
  nextBarSpacing,
  shortMarkerSpan,
  validPriceRange,
  validTimeRange,
} from '../src/lib/chartViewport.js'

test('chart zoom stays in MT5-like discrete spacing bounds', () => {
  assert.equal(clampBarSpacing(100), 48)
  assert.equal(clampBarSpacing(-1), 2)
  assert.equal(clampBarSpacing('bad'), 16)
  assert.equal(nextBarSpacing(8, 1), 12)
  assert.equal(nextBarSpacing(8, -1), 6)
  assert.equal(nextBarSpacing(48, 1), 48)
  assert.equal(nextBarSpacing(2, -1), 2)
})

test('latest range retains a bounded view and configurable right margin', () => {
  assert.deepEqual(latestLogicalRange(100, 40, 8), { from: 67, to: 107 })
  assert.equal(latestLogicalRange(0, 40), null)
  assert.equal(latestLogicalRange(100, 0).from, 97)
})

test('saved time viewport restores only when the selected candle data covers it', () => {
  assert.equal(validTimeRange({ from: 20, to: 40 }, 10, 50), true)
  assert.equal(validTimeRange({ from: 20, to: 60 }, 10, 50), false)
  assert.equal(validTimeRange({ from: 40, to: 20 }, 10, 50), false)
})

test('short protection markers stay inside the chart plot area', () => {
  assert.deepEqual(shortMarkerSpan(800), { left: 590, right: 722 })
  assert.deepEqual(shortMarkerSpan(100), { left: 0, right: 22 })
  assert.equal(shortMarkerSpan(70), null)
})

test('position overlays accept the canonical symbol and a dotted broker suffix only', () => {
  assert.equal(matchesChartSymbol('XAUUSD', 'XAUUSD'), true)
  assert.equal(matchesChartSymbol('XAUUSD.s', 'XAUUSD'), true)
  assert.equal(matchesChartSymbol('EURUSD', 'XAUUSD'), false)
  assert.equal(matchesChartSymbol('XAUUSDm', 'XAUUSD'), false)
})

test('fixed price range rejects blank, non-finite and reversed bounds', () => {
  assert.deepEqual(validPriceRange('10', '11'), { minValue: 10, maxValue: 11 })
  assert.equal(validPriceRange('', '11'), null)
  assert.equal(validPriceRange('Infinity', '11'), null)
  assert.equal(validPriceRange('11', '10'), null)
})
