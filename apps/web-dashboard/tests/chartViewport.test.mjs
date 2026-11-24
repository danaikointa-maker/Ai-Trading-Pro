import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

import {
  canApplyLiveQuote,
  clampBarSpacing,
  followLatestTimeRange,
  fullPlotLineSpan,
  latestLogicalRange,
  matchesChartSymbol,
  needsCandleReloadOnRecovery,
  nextBarCount,
  nextBarSpacing,
  priceLineDash,
  shouldResetPriceScaleForViewChange,
  stabilizeAutoscaleInfo,
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

test('following the latest candle changes only the horizontal viewport', () => {
  const applied = []
  const chart = {
    timeScale: () => ({ setVisibleLogicalRange: range => applied.push(range) }),
    priceScale: () => { throw new Error('latest-bar follow must preserve vertical zoom') },
  }
  const range = { from: 20, to: 60 }
  assert.equal(followLatestTimeRange(chart, range), true)
  assert.deepEqual(applied, [range])
  assert.equal(followLatestTimeRange(chart, null), false)
})

test('price autoscale resets only when feed, symbol, or timeframe changes', () => {
  assert.equal(shouldResetPriceScaleForViewChange('', 'mt5:XAUUSD:M5'), false)
  assert.equal(shouldResetPriceScaleForViewChange('mt5:XAUUSD:M5', 'mt5:XAUUSD:M5'), false)
  assert.equal(shouldResetPriceScaleForViewChange('mt5:XAUUSD:M5', 'mt5:XAUUSD:M15'), true)
  assert.equal(shouldResetPriceScaleForViewChange('mt5:XAUUSD:M5', 'sim:XAUUSD:M5'), true)
})

test('automatic price following translates a fixed range instead of shrinking candles', () => {
  const first = { priceRange: { minValue: 2000, maxValue: 2020 }, margins: { above: 8, below: 6 } }
  const initialized = stabilizeAutoscaleInfo(first, 2010, null)
  assert.equal(initialized.span, 20)
  assert.equal(initialized.center, 2010)
  assert.equal(initialized.info, first)

  const next = stabilizeAutoscaleInfo({ priceRange: { minValue: 2005, maxValue: 2035 }, margins: first.margins }, 2025, initialized.span, initialized.center)
  assert.deepEqual(next.info.priceRange, { minValue: 2015, maxValue: 2035 })
  assert.deepEqual(next.info.margins, first.margins)
  assert.equal(next.span, 20)
  assert.equal(next.center, 2025)

  const held = stabilizeAutoscaleInfo({ priceRange: { minValue: 2020, maxValue: 2060 } }, null, next.span, next.center)
  assert.deepEqual(held.info.priceRange, next.info.priceRange)
  assert.equal(held.center, next.center)

  const later = stabilizeAutoscaleInfo({ priceRange: { minValue: 2020, maxValue: 2060 } }, 2040, next.span, held.center)
  assert.deepEqual(later.info.priceRange, { minValue: 2030, maxValue: 2050 })
  assert.equal(later.info.priceRange.maxValue - later.info.priceRange.minValue, 20)
  assert.equal(later.center, 2040)
})

test('PriceChart uses the fixed-span provider for candles only', async () => {
  const source = await readFile(new URL('../src/components/PriceChart.vue', import.meta.url), 'utf8')
  assert.match(source, /autoscaleInfoProvider:\s*\(original\)\s*=>/)
  assert.match(source, /stabilizeAutoscaleInfo\(/)
  assert.match(source, /autoScroll\.value\s*\?\s*lastCandle\?\.close\s*:\s*null/)
  assert.match(source, /autoscaleInfoProvider:\s*\(\)\s*=>\s*null/)
  const follow = source.match(/function goLatest\(\)\s*\{([\s\S]*?)\n\}/)?.[1] || ''
  assert.doesNotMatch(follow, /priceScale|autoScale/)
})

test('analysis level canvas lines use the plot area and preserve line styles', () => {
  assert.deepEqual(fullPlotLineSpan(640), { left: 0, right: 640 })
  assert.equal(fullPlotLineSpan(0), null)
  assert.deepEqual(priceLineDash(0), [])
  assert.deepEqual(priceLineDash(1), [2, 3])
  assert.deepEqual(priceLineDash(2), [5, 3])
  assert.deepEqual(priceLineDash(3), [10, 4, 3, 4])
  assert.deepEqual(priceLineDash(4), [1, 4])
})

test('appending a new candle advances the latest-bar count', () => {
  assert.equal(nextBarCount(240), 241)
  assert.equal(nextBarCount(0), 1)
  assert.equal(nextBarCount(Number.NaN), 1)
})

test('candle history reloads only on a confirmed stream, API, or quote recovery', () => {
  assert.equal(needsCandleReloadOnRecovery(
    { connected: false }, { connected: true },
  ), true)
  assert.equal(needsCandleReloadOnRecovery(
    { serverUnreachable: true }, { serverUnreachable: false },
  ), true)
  assert.equal(needsCandleReloadOnRecovery(
    { tickerStale: true }, { tickerStale: false, hasTick: true },
  ), true)
  assert.equal(needsCandleReloadOnRecovery(
    { tickerStale: true }, { tickerStale: false, hasTick: false },
  ), false)
  assert.equal(needsCandleReloadOnRecovery(
    { connected: true, serverUnreachable: false, tickerStale: false },
    { connected: true, serverUnreachable: false, tickerStale: false },
  ), false)
})

test('stale or disconnected quotes never mutate the current candle', () => {
  const tick = { t: 100, last: 2000 }
  assert.equal(canApplyLiveQuote(tick, false, false), true)
  assert.equal(canApplyLiveQuote(tick, true, false), false)
  assert.equal(canApplyLiveQuote(tick, false, true), false)
  assert.equal(canApplyLiveQuote(null, false, false), false)
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
