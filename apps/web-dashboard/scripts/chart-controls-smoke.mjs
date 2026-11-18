import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { latestLogicalRange, nextBarSpacing, validPriceRange } from '../src/lib/chartViewport.js'

const storage = new Map()
globalThis.localStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) }
globalThis.window = new EventTarget()
window.localStorage = globalThis.localStorage
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
try {
  const prefs = await server.ssrLoadModule('/src/lib/chartTimeframes.js')
  const store = await server.ssrLoadModule('/src/lib/store.js')
  const { default: Picker } = await server.ssrLoadModule('/src/components/TimeframePicker.vue')
  assert.ok(prefs.pinnedTimeframes.value.includes('M3'))
  assert.equal(prefs.timeframeSeconds('M3'), 180)
  assert.deepEqual(prefs.normalizeTimeframes(['INVALID', 'M3', 'M3', 'M1']), ['M1', 'M3'])
  store.setTimeframe('M3')
  prefs.toggleTimeframe('M3')
  assert.equal(store.state.timeframe, 'M3', 'hiding the active button must not switch the chart')
  assert.ok(!prefs.pinnedTimeframes.value.includes('M3'))
  await nextTick()
  assert.ok(!JSON.parse(storage.get('no7.chart.timeframes.v1')).includes('M3'))
  const html = await renderToString(createSSRApp(Picker))
  assert.match(html, /กำลังดู M3/)
  assert.match(html, /แสดงปุ่ม M30/)
  assert.match(html, /แสดงปุ่ม D1/)
  for (const tf of [...prefs.pinnedTimeframes.value]) prefs.toggleTimeframe(tf)
  assert.equal(prefs.pinnedTimeframes.value.length, 1, 'retain an accessible timeframe button')
  prefs.resetTimeframes()
  assert.ok(prefs.pinnedTimeframes.value.includes('M3'))
  assert.equal(nextBarSpacing(16, 1), 24)
  assert.equal(nextBarSpacing(2, -1), 2)
  const range = latestLogicalRange(240, 60, 12)
  assert.equal(range.to - range.from, 60)
  assert.equal(range.to, 251)
  assert.equal(validPriceRange('', 10), null)
  assert.equal(validPriceRange(10, 5), null)
  assert.deepEqual(validPriceRange('3762.46', '3791.02'), { minValue: 3762.46, maxValue: 3791.02 })
  const { default: Chart } = await server.ssrLoadModule('/src/components/PriceChart.vue')
  const app = createSSRApp(Chart)
  app.component('RouterLink', { template: '<a><slot /></a>' })
  app.config.warnHandler = message => { throw new Error(message) }
  assert.match(await renderToString(app), /ควบคุมกราฟ/)
  console.log('PASS: timeframe visibility, persistence, active selection, viewport helpers and chart SSR')
} finally { await server.close() }
