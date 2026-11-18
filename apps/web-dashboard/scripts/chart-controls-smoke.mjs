import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp, h, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import { latestLogicalRange, nextBarSpacing, validPriceRange } from '../src/lib/chartViewport.js'
import { singleFlight } from '../src/lib/singleFlight.js'

const storage = new Map()
globalThis.localStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) }
globalThis.window = new EventTarget()
window.localStorage = globalThis.localStorage
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
try {
  let release, requests = 0
  const refresh = singleFlight(() => { requests++; return new Promise(resolve => { release = resolve }) })
  const first = refresh()
  await refresh()
  await refresh()
  assert.equal(requests, 1, 'slow requests must not pile up when multiple timer ticks arrive')
  release()
  await first
  const next = refresh()
  assert.equal(requests, 2, 'refresh must resume after completion')
  release()
  await next
  let failures = 0
  const failingRefresh = singleFlight(async () => { failures++; throw new Error('fixture timeout') })
  await assert.rejects(failingRefresh(), /timeout/)
  await assert.rejects(failingRefresh(), /timeout/)
  assert.equal(failures, 2, 'failure must release the in-flight guard')
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
  const twoPickers = createSSRApp({ render: () => h('div', [h(Picker), h(Picker)]) })
  const selectedHtml = await renderToString(twoPickers)
  const activeM3Buttons = [...selectedHtml.matchAll(/<button\b[^>]*aria-pressed="true"[^>]*aria-current="true"[^>]*>M3<\/button>/g)]
  assert.equal(activeM3Buttons.length, 4, 'both toolbars and both menus must mark the chosen M3')
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
  const chartHtml = await renderToString(app)
  assert.match(chartHtml, /ควบคุมกราฟ/)
  // Icon controls must keep a readable name after their visible text is removed.
  function checkIconNames(html) {
    let checked = 0
    for (const match of html.matchAll(/<(button|summary)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
      if (!match[3].includes('<svg')) continue
      assert.match(match[2], /aria-label="[^"]+"/, 'icon control must have an accessible name')
      assert.match(match[2], /title="[^"]+"/, 'icon control must have a hover explanation')
      checked++
    }
    assert.ok(checked > 0)
  }
  checkIconNames(chartHtml)
  // A fresh module must restore a previously hidden desktop menu.
  storage.set('no7.sidebar.expanded.v1', 'false')
  const sidebar = await server.ssrLoadModule('/src/lib/sidebar.js')
  assert.equal(sidebar.sidebarExpanded.value, false)
  assert.equal(sidebar.sidebarOpen.value, false)
  sidebar.toggleSidebar()
  assert.equal(sidebar.sidebarExpanded.value, true)
  assert.equal(storage.get('no7.sidebar.expanded.v1'), 'true')
  sidebar.toggleSidebar()
  assert.equal(storage.get('no7.sidebar.expanded.v1'), 'false')
  sidebar.desktopSidebar.value = false
  sidebar.toggleSidebar()
  assert.equal(sidebar.mobileSidebarOpen.value, true)
  assert.equal(storage.get('no7.sidebar.mobile-open.v1'), 'true')
  assert.equal(sidebar.sidebarTarget.value, 'mobile-sidebar')
  sidebar.closeMobileSidebar()
  assert.equal(sidebar.sidebarExpanded.value, false, 'closing a mobile drawer cannot expand desktop layout')
  sidebar.desktopSidebar.value = true
  const savePreference = localStorage.setItem
  localStorage.setItem = () => { throw new Error('fixture storage unavailable') }
  sidebar.toggleSidebar()
  assert.equal(sidebar.sidebarOpen.value, true, 'a storage failure must not disable the menu control')
  localStorage.setItem = savePreference
  sidebar.toggleSidebar()
  const { default: Header } = await server.ssrLoadModule('/src/components/TopBar.vue')
  const headerApp = createSSRApp(Header)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  headerApp.use(router)
  await router.push('/')
  await router.isReady()
  headerApp.config.warnHandler = message => { throw new Error(message) }
  const headerHtml = await renderToString(headerApp)
  checkIconNames(headerHtml)
  assert.match(headerHtml, /aria-expanded="false" aria-controls="app-sidebar"/)
  assert.match(headerHtml, /แสดงเมนูซ้าย/)
  const { default: SideNav } = await server.ssrLoadModule('/src/components/SideNav.vue')
  const mobileNav = createSSRApp(SideNav, { mobile: true })
  mobileNav.component('RouterLink', { template: '<a><slot /></a>' })
  mobileNav.config.warnHandler = message => { throw new Error(message) }
  const navHtml = await renderToString(mobileNav)
  assert.match(navHtml, /role="dialog" aria-modal="true"/)
  assert.match(navHtml, /ปิดเมนูซ้าย/)
  assert.match(navHtml, /Terminal/)
  console.log('PASS: sidebar restoration/toggle/mobile persistence, timeframe preferences, accessible controls and chart helpers')
} finally { await server.close() }
