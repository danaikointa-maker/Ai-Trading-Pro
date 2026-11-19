import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { parse, compileScript } from '@vue/compiler-sfc'
import { baseParse } from '@vue/compiler-dom'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

// Audit real template bindings without clicking a trading or account action.
function files(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory()
    ? files(resolve(dir, entry.name)) : entry.name.endsWith('.vue') ? [resolve(dir, entry.name)] : [])
}
let handlers = 0
for (const file of files(resolve('src'))) {
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file })
  if (!descriptor.template) continue
  const script = compileScript(descriptor, { id: file })
  const aliases = new Set(['$emit', '$event'])
  const nodes = []
  function collect(node) {
    nodes.push(node)
    for (const prop of node.props || []) {
      if (prop.type === 7 && prop.name === 'for') {
        for (const id of (prop.exp?.content.split(/\s+(?:in|of)\s+/)[0].match(/[A-Za-z_$][\w$]*/g) || [])) aliases.add(id)
      }
      if (prop.type === 7 && prop.name === 'slot') {
        for (const id of prop.exp?.content.match(/[A-Za-z_$][\w$]*/g) || []) aliases.add(id)
      }
    }
    for (const child of node.children || []) collect(child)
  }
  collect(baseParse(descriptor.template.content))
  for (const node of nodes) for (const prop of node.props || []) {
    if (prop.type !== 7 || prop.name !== 'on' || !prop.exp) continue
    const first = prop.exp.content.match(/^\s*([A-Za-z_$][\w$]*)/)?.[1]
    if (first && !['async', 'event'].includes(first)) {
      assert.ok(first in script.bindings || aliases.has(first), `${file}: missing handler binding ${prop.exp.content}`)
      handlers++
    }
  }
}

const storage = new Map()
globalThis.localStorage = { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) }
globalThis.window = new EventTarget()
window.localStorage = globalThis.localStorage
globalThis.document = { fullscreenElement: null, exitFullscreen: async () => { document.fullscreenElement = null } }
globalThis.requestAnimationFrame = () => 1
globalThis.cancelAnimationFrame = () => {}
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
try {
  const { default: Chart } = await server.ssrLoadModule('/src/components/PriceChart.vue')
  let controls
  const TestChart = { ...Chart, setup(props, context) { controls = Chart.setup(props, context); return controls } }
  const app = createSSRApp(TestChart)
  app.component('RouterLink', { template: '<a><slot /></a>' })
  app.config.warnHandler = message => { throw new Error(message) }
  await renderToString(app)
  assert.equal(typeof controls.zoom, 'function')
  let spacing = 16, logical = null, range = { from: 900, to: 2520 }, fitCalls = 0
  const priceOptions = [], chartOptions = [], scrollPositions = [], zoneStrokes = []
  const timeScale = {
    width: () => 600, options: () => ({ barSpacing: spacing }),
    applyOptions: o => { spacing = o.barSpacing ?? spacing },
    getVisibleRange: () => range, setVisibleRange: r => { range = r }, timeToCoordinate: () => 560,
    setVisibleLogicalRange: r => { logical = r }, getVisibleLogicalRange: () => logical,
    fitContent: () => { fitCalls++ }, scrollPosition: () => 0, scrollToPosition: value => scrollPositions.push(value),
  }
  controls.chart = { timeScale: () => timeScale, priceScale: () => ({ applyOptions: o => priceOptions.push(o) }), applyOptions: o => chartOptions.push(o) }
  controls.candleSeries = { data: () => Array.from({ length: 10 }, (_, i) => ({ time: 900 + i * 180 })),
    priceToCoordinate: price => price >= 0 && price < 100 ? 50 : null,
    createPriceLine: options => { toolLines.push(options); return options }, removePriceLine: () => {} }
  controls.bars.value = 10
  controls.spacing.value = 16
  controls.zoom(1)
  assert.equal(spacing, 24)
  controls.zoom(-1)
  assert.equal(spacing, 16)
  controls.toggleAutoScroll()
  assert.equal(controls.autoScroll.value, false)
  controls.goLatest()
  assert.equal(controls.autoScroll.value, true)
  assert.ok(logical.to > 9)
  controls.toggleShift()
  assert.equal(controls.chartShift.value, false)
  controls.fitAll()
  assert.equal(fitCalls, 1)
  assert.equal(controls.autoScroll.value, false)
  const keyboard = key => ({ key, target: { closest: () => null }, preventDefault() {} })
  controls.chartKeydown(keyboard('ArrowLeft'))
  controls.chartKeydown(keyboard('ArrowRight'))
  assert.deepEqual(scrollPositions, [-10, 10], 'left moves into history, right toward newer bars')
  controls.priceMin.value = '10'
  controls.priceMax.value = '5'
  controls.applyFixedPrice()
  assert.equal(controls.fixedPriceRange.value, null)
  assert.ok(controls.viewError.value)
  controls.priceMax.value = '20'
  controls.applyFixedPrice()
  assert.equal(controls.fixedPriceRange.value.maxValue, 20)
  assert.equal(priceOptions.at(-1).scaleMargins.top, 0)
  controls.resetPriceScale()
  assert.equal(controls.fixedPriceRange.value, null)
  assert.equal(priceOptions.at(-1).autoScale, true)
  controls.timeFrom.value = '1970-01-01T00:15'
  controls.timeTo.value = '1970-01-01T00:24'
  controls.applyTimeRange()
  assert.equal(range.from, 900)
  assert.equal(range.to, 1440)
  controls.timeFrom.value = '1969-01-01T00:15'
  controls.applyTimeRange()
  assert.match(controls.viewError.value, /นอกข้อมูล/)
  const host = { requestFullscreen: async () => { document.fullscreenElement = controls.chartHost.value } }
  controls.chartHost.value = host
  await controls.toggleFullscreen()
  controls.fullscreenChanged()
  assert.equal(controls.fullscreen.value, true)
  await controls.toggleFullscreen()
  controls.fullscreenChanged()
  assert.equal(controls.fullscreen.value, false)
  controls.chartFeed.value = 'mt5-live'
  controls.selectedAccount.value = 'fixture-account'
  assert.equal(controls.layerUnavailable('plan'), false)
  assert.equal(controls.layerUnavailable('ema'), false)
  const toolLines = []
  controls.candleSeries.createPriceLine = options => { toolLines.push(options); return options }
  controls.candleSeries.removePriceLine = () => {}
  controls.chartOverlays.value = { available: true,
    supports: [{ mid: 10, quality: 'high' }], resistances: [],
    fibonacci_band: { level_50: 12, level_618: 11 },
    sr_flips: [{ level: 14, direction: 'resistance_to_support' }],
    structure: [{ level: 15, kind: 'BOS', confirmed: true }] }
  controls.lastCandle = { time: 2520 }
  const context = { setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {},
    stroke() { zoneStrokes.push(true) }, setLineDash() {}, fillText() {}, fillRect() {} }
  controls.segmentCanvas.value = { style: {}, set width(value) {}, set height(value) {}, getContext: () => context }
  controls.container.value = { clientWidth: 700, clientHeight: 500 }
  globalThis.window.devicePixelRatio = 1
  for (const key of ['sr', 'flip', 'fib', 'structure']) {
    assert.equal(controls.layerUnavailable(key), false, `same-source ${key} must be usable`)
    controls.layerVisibility[key] = true
  }
  assert.equal(controls.layerUnavailable('positions'), false)
  controls.drawOverlays()
  assert.equal(zoneStrokes.length, 4, 'renders zone bounds plus flip and structure lines')
  controls.chartPositions.value = { available: true, positions: [{ ticket: 'fixture-private', entry: 20, sl: 18, tp: 24 }], reason: '' }
  controls.layerVisibility.positions = true
  controls.layerVisibility.plan = true
  toolLines.length = 0
  controls.drawOverlays()
  assert.ok(toolLines.some(line => line.price === 20))
  assert.ok(toolLines.some(line => line.price === 18))
  assert.ok(toolLines.some(line => line.price === 24))
  controls.toggleLayer('positions')
  toolLines.length = 0
  controls.drawOverlays()
  assert.ok(!toolLines.some(line => line.price === 20), 'POS hides entry independently')
  assert.ok(toolLines.some(line => line.price === 18), 'SL/TP stays visible when POS is hidden')
  controls.chartOverlays.value.sr_flips = []
  controls.layerVisibility.flip = false
  controls.toggleLayer('flip')
  assert.match(controls.layerNote.value, /ยังไม่พบ FLIP/)
  controls.chartHeight.value = 900
  controls.mt5View()
  assert.equal(controls.chartHeight.value, 580, 'MT5 preset must apply the height advertised by its tooltip')
  assert.equal(controls.layerVisibility.ema, false)
  assert.equal(controls.chartShift.value, true)
  const store = await server.ssrLoadModule('/src/lib/store.js')
  const { api } = await server.ssrLoadModule('/src/lib/api.js')
  const post = api.post
  const requests = []
  try {
    api.post = async (url, payload) => { requests.push({ url, payload }); return { ok: true, mode: payload.mode } }
    store.state.user = { role: 'viewer' }
    await assert.rejects(store.changeTradingMode('semi_auto'), /viewer/)
    assert.equal(requests.length, 0)
    store.state.user = { role: 'trader' }
    store.state.config = { security: { allow_full_auto: false, full_auto_enabled: false } }
    await assert.rejects(store.changeTradingMode('full_auto'), /ล็อก/)
    assert.equal(requests.length, 0)
    store.state.live = { mode: 'manual' }
    await store.changeTradingMode('semi_auto')
    assert.equal(store.mode.value, 'semi_auto')
    assert.equal(store.state.live.mode, 'semi_auto')
    assert.equal(store.state.trading.mode, 'semi_auto')
    assert.equal(requests.length, 1)
    api.post = async () => { throw new Error('fixture request refused') }
    await assert.rejects(store.changeTradingMode('manual'), /refused/)
    assert.equal(store.mode.value, 'semi_auto', 'failed requests cannot light up the requested mode')
    assert.equal(store.modeChanging.value, false)
  } finally { api.post = post }
  const { default: Brokers } = await server.ssrLoadModule('/src/views/Brokers.vue')
  let manager
  const TestBrokers = { ...Brokers, setup(props, context) { manager = Brokers.setup(props, context); return manager } }
  const brokerApp = createSSRApp(TestBrokers)
  brokerApp.component('RouterLink', { template: '<a><slot /></a>' })
  store.state.user = { role: 'trader', tenant_id: 'default' }
  await renderToString(brokerApp)
  const originalApi = { get: api.get, put: api.put, del: api.del }
  const mutations = []
  try {
    api.get = async path => path === '/api/teams' ? { teams: [] } : path === '/api/market/context' ? { accounts: [] } : { accounts: [] }
    api.put = async (url, body) => { mutations.push({ method: 'PUT', url, body }); return { ok: true } }
    api.del = async url => { mutations.push({ method: 'DELETE', url }); return { ok: true } }
    const account = { id: 'fixture-account', label: 'Gold Demo', server: 'Demo', login: '****1234',
      can_manage: true, updated_at: 100, terminal_path: 'terminal64.exe', account_type: 'demo', validation_symbol: 'XAUUSD.s' }
    manager.startAccountEdit(account)
    manager.editDraft.value.password = 'fixture-unsaved'
    manager.cancelAccountEdit()
    assert.deepEqual(manager.editDraft.value, {})
    assert.equal(mutations.length, 0, 'cancel edit must not write')
    manager.startAccountEdit(account)
    manager.editDraft.value.label = 'Renamed Demo'
    await manager.saveAccountEdit()
    assert.equal(mutations[0].body.label, 'Renamed Demo')
    assert.equal(mutations[0].body.expected_updated_at, 100)
    await manager.requestRemoval('account', account)
    manager.cancelRemoval()
    assert.equal(mutations.length, 1, 'cancel deletion must not send DELETE')
    await manager.requestRemoval('account', account)
    api.del = async () => { throw new Error('stale fixture') }
    await manager.confirmRemoval()
    assert.match(manager.removalError.value, /stale/)
    assert.ok(manager.removal.value, 'failed delete stays reviewable')
    api.del = async url => { mutations.push({ method: 'DELETE', url }); return { ok: true } }
    await manager.confirmRemoval()
    assert.match(mutations.at(-1).url, /expected_updated_at=100/)
    assert.equal(manager.removal.value, null)
    manager.startTerminalEdit({ id: 'fixture-link', label: 'Old' })
    manager.terminalEdit.value.label = 'New'
    await manager.saveTerminalLabel()
    assert.deepEqual(mutations.at(-1).body, { label: 'New', expected_label: 'Old' })
    store.state.user = { role: 'viewer', tenant_id: 'default' }
    manager.startAccountEdit(account)
    await manager.requestRemoval('account', account)
    assert.equal(manager.editingAccount.value, null)
    assert.equal(manager.removal.value, null)
  } finally { Object.assign(api, originalApi) }
  console.log(`PASS: ${handlers} template event bindings audited; chart, broker edit/cancel/delete/rename and role guards exercised with mocked API only`)
} finally { await server.close() }
