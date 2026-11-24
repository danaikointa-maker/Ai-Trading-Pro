<template>
  <div class="relative">
    <div class="flex flex-wrap items-center gap-1.5 border-b border-ink-700/60 px-2 py-2" aria-label="ชั้นข้อมูลบนกราฟ">
      <span class="mr-1 text-[10px] text-muted">แสดงเส้น:</span>
      <button v-for="item in layerChoices" :key="item.key" type="button"
              class="rounded border px-2 py-1 text-[10px] transition-colors"
              :class="layerVisibility[item.key] ? 'border-gold/50 bg-gold/10 text-gold' : 'border-ink-700 text-muted'"
              :aria-pressed="layerVisibility[item.key]" :title="'เปิด/ปิดเฉพาะการแสดงผล ' + item.label"
              @click="layerVisibility[item.key] = !layerVisibility[item.key]">
        {{ item.label }} {{ layerVisibility[item.key] ? '✓' : '○' }}
      </button>
      <span class="text-[9.5px] text-muted">ไม่กระทบระบบเทรด</span>
    </div>
    <div class="flex flex-wrap items-center gap-1 border-b border-ink-700/60 px-2 py-1.5" aria-label="ควบคุมมุมมองกราฟ">
      <button class="btn px-2 py-1 text-[10px]" :disabled="!bars || loading" aria-label="ซูมออก" title="ซูมออก" @click="zoom(-1)">−</button>
      <button class="btn px-2 py-1 text-[10px]" :disabled="!bars || loading" aria-label="ซูมเข้า" title="ซูมเข้า" @click="zoom(1)">+</button>
      <label class="flex items-center gap-1 text-[9px] text-muted" title="ความกว้างแท่งเป็นพิกเซล">
        px <input class="input w-14 py-1 text-[10px]" type="number" min="2" max="48" step="1" :value="spacing" aria-label="ความกว้างแท่ง" @change="setSpacing($event.target.value)" />
      </label>
      <button class="btn px-2 py-1 text-[9px]" :aria-pressed="autoScroll" aria-label="เลื่อนตามแท่งล่าสุดอัตโนมัติ" title="ติดตามแท่งล่าสุด" @click="toggleAutoScroll">{{ autoScroll ? 'LIVE ✓' : 'LIVE ○' }}</button>
      <button class="btn px-2 py-1 text-[9px]" :aria-pressed="chartShift" aria-label="เว้นที่ว่างด้านขวาของกราฟ" title="Chart shift" @click="toggleShift">SHIFT {{ chartShift ? '✓' : '○' }}</button>
      <button class="btn px-2 py-1 text-[9px]" :disabled="!bars || loading" aria-label="กลับไปแท่งล่าสุด" title="แท่งล่าสุด" @click="goLatest">ล่าสุด</button>
      <button class="btn px-2 py-1 text-[9px]" :disabled="!bars || loading" aria-label="แสดงแท่งทั้งหมดที่โหลด" title="Fit all" @click="fitAll">ทั้งหมด</button>
    </div>
    <div class="relative">
      <div ref="container" class="h-[380px] w-full sm:h-[440px]"
           @pointerdown="startChartDrag" @pointermove="moveChartDrag" @pointerup="endChartDrag"
           @pointercancel="endChartDrag" @pointerleave="endChartDrag"></div>
      <canvas ref="segmentCanvas" class="pointer-events-none absolute inset-0 z-10" aria-hidden="true"></canvas>
    </div>
    <div class="pointer-events-none absolute left-3 top-12 flex flex-wrap items-center gap-1.5">
      <span class="chip chip-gold">{{ state.symbol }} · {{ state.timeframe }}</span>
      <span class="chip" :class="feedWarn ? 'chip-warn' : ''" :title="feedTitle">{{ feedLabel }}</span>
      <span v-if="displayBasis === 'broker_server'" class="chip" title="แสดงเวลาโบรกเกอร์; timestamp ภายในระบบยังเป็น UTC">MT5 UTC{{ offsetLabel }}</span>
      <span v-if="state.live?.analysis?.regime" class="chip">{{ state.live.analysis.regime.regime.replace('_',' ') }}</span>
    </div>
    <div v-if="loading" class="absolute inset-x-0 bottom-0 top-10 grid place-items-center bg-ink-900/40 text-[12px] text-muted">loading chart…</div>
    <!-- Never fail silently: a blank panel tells nobody anything. -->
    <div v-else-if="error" class="absolute inset-0 grid place-items-center px-6 text-center">
      <div>
        <div class="text-[12.5px] font-semibold text-down">แสดงกราฟไม่ได้</div>
        <div class="mt-1 max-w-[520px] break-words text-[11px] leading-relaxed text-muted">{{ error }}</div>
        <button class="btn mt-3 px-3 py-1.5 text-[11.5px]" @click="retry">ลองอีกครั้ง</button>
      </div>
    </div>
    <div v-else-if="bars === 0" class="absolute inset-0 grid place-items-center px-6 text-center">
      <div>
        <div class="text-[12.5px] font-semibold text-slate-200">ยังไม่มีข้อมูลแท่งเทียน</div>
        <div class="mt-1 text-[11px] text-muted">{{ state.symbol }} · {{ state.timeframe }} — รอ feed ส่งข้อมูล</div>
        <button class="btn mt-3 px-3 py-1.5 text-[11.5px]" @click="retry">โหลดใหม่</button>
      </div>
    </div>
    <div class="pointer-events-none absolute bottom-1.5 right-2 text-[9.5px] text-muted">
      {{ bars }} bars · last {{ lastBarText }}
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'
import { api } from '../lib/api'
import { positions, state } from '../lib/store'
import { canApplyLiveQuote, clampBarSpacing, latestLogicalRange, matchesChartSymbol, needsCandleReloadOnRecovery, nextBarCount, nextBarSpacing, shortMarkerSpan, validPriceRange, validTimeRange } from '../lib/chartViewport'

const container = ref(null)
const segmentCanvas = ref(null)
const loading = ref(false)
const error = ref('')
const bars = ref(0)
const lastBar = ref(null)
let chart = null
let candleSeries = null
let ema20 = null
let ema50 = null
let ema200 = null
let priceLines = []
let shortMarkers = []
let lastCandle = null
let resizeObs = null
let priceDigits = 2
let loadedViewKey = ''
let viewportFrame = null
let viewportSaveTimer = null
let markerFrame = null
let recoveryRefreshTimer = null
let candleLoadRequestId = 0
let dragOrigin = null
const VIEW_PREFS_KEY = 'no7.chart.viewport.v1'
let savedPrefs = {}
try { savedPrefs = JSON.parse(localStorage.getItem(VIEW_PREFS_KEY) || '{}') || {} } catch { /* preferences are optional */ }
const spacing = ref(clampBarSpacing(savedPrefs.spacing))
const chartShift = ref(savedPrefs.chartShift !== false)
const autoScroll = ref(savedPrefs.autoScroll !== false)
const displayOffsetSeconds = ref(0)
const displayBasis = ref('utc')
const offsetLabel = computed(() => {
  const hours = displayOffsetSeconds.value / 3600
  return `${hours >= 0 ? '+' : ''}${hours}`
})

function formatServerClock(timestamp) {
  if (typeof timestamp !== 'number') return ''
  return new Date((timestamp + displayOffsetSeconds.value) * 1000).toLocaleTimeString('en-GB', {
    timeZone: 'UTC', hour: '2-digit', minute: '2-digit',
  })
}

function saveViewPrefs() {
  try {
    localStorage.setItem(VIEW_PREFS_KEY, JSON.stringify({
      spacing: spacing.value, chartShift: chartShift.value, autoScroll: autoScroll.value,
    }))
    const range = chart?.timeScale().getVisibleRange()
    if (range && loadedViewKey && !autoScroll.value) {
      localStorage.setItem(`${VIEW_PREFS_KEY}:${loadedViewKey}`, JSON.stringify(range))
    }
  } catch { /* private mode or invalid preference storage is non-fatal */ }
}

function syncViewport() {
  if (viewportFrame) cancelAnimationFrame(viewportFrame)
  viewportFrame = requestAnimationFrame(() => {
    if (!chart || !container.value) return
    spacing.value = clampBarSpacing(chart.timeScale().options().barSpacing)
    const visible = chart.timeScale().getVisibleLogicalRange()
    if (autoScroll.value && bars.value > 0 && visible && visible.to < bars.value - 1 - 1) {
      autoScroll.value = false
    }
    clearTimeout(viewportSaveTimer)
    viewportSaveTimer = setTimeout(saveViewPrefs, 200)
    drawShortMarkers()
  })
}

function latestRange() {
  if (!chart) return null
  const visibleBars = chart.timeScale().width() / spacing.value
  return latestLogicalRange(bars.value, visibleBars, chartShift.value ? 8 : 1)
}

function goLatest() {
  const range = latestRange()
  if (!chart || !range) return
  autoScroll.value = true
  chart.priceScale('right').applyOptions({ autoScale: true })
  chart.timeScale().setVisibleLogicalRange(range)
  saveViewPrefs()
}

function setSpacing(value) {
  spacing.value = clampBarSpacing(value)
  chart?.timeScale().applyOptions({ barSpacing: spacing.value })
  if (autoScroll.value) goLatest()
  syncViewport()
}

function zoom(direction) { setSpacing(nextBarSpacing(spacing.value, direction)) }

function toggleAutoScroll() {
  autoScroll.value = !autoScroll.value
  if (autoScroll.value) goLatest()
  saveViewPrefs()
}

function toggleShift() {
  chartShift.value = !chartShift.value
  chart?.timeScale().applyOptions({ rightOffset: chartShift.value ? 8 : 1 })
  if (autoScroll.value) goLatest()
  saveViewPrefs()
}

function fitAll() {
  if (!chart || !bars.value) return
  autoScroll.value = false
  chart.timeScale().fitContent()
  syncViewport()
}

function startChartDrag(event) { dragOrigin = { x: event.clientX, y: event.clientY } }
function moveChartDrag(event) {
  if (event.buttons) scheduleMarkerRedraw()
  if (!dragOrigin || !event.buttons) return
  if (Math.abs(event.clientX - dragOrigin.x) > 4 || Math.abs(event.clientY - dragOrigin.y) > 4) {
    autoScroll.value = false
    saveViewPrefs()
  }
}
function endChartDrag() {
  dragOrigin = null
  scheduleMarkerRedraw()
}

function scheduleMarkerRedraw() {
  if (markerFrame) cancelAnimationFrame(markerFrame)
  markerFrame = requestAnimationFrame(() => {
    markerFrame = null
    drawShortMarkers()
  })
}

// UI preferences only: never write these switches into state.live or send an
// API request. Engine, risk controls and persisted trade decisions are unchanged.
const LAYERS_KEY = 'no7.chart.layers.v1'
const layerChoices = [
  { key: 'ema', label: 'EMA' },
  { key: 'sr', label: 'S/R' },
  { key: 'flip', label: 'SR Flip' },
  { key: 'fib', label: 'Fib 50–61.8' },
  { key: 'structure', label: 'BOS/CHoCH' },
  { key: 'plan', label: 'Entry/SL/TP' },
  { key: 'positions', label: 'ไม้เปิด' },
]
const layerVisibility = reactive({ ema: true, sr: true, flip: true, fib: true, structure: false, plan: true, positions: true })
try {
  const saved = JSON.parse(window.localStorage.getItem(LAYERS_KEY) || '{}')
  for (const { key } of layerChoices) {
    if (typeof saved[key] === 'boolean') layerVisibility[key] = saved[key]
  }
} catch { /* Private mode or invalid preferences: defaults remain safe. */ }

function syncSeriesVisibility() {
  for (const series of [ema20, ema50, ema200]) series?.applyOptions({ visible: layerVisibility.ema })
}

watch(layerVisibility, () => {
  syncSeriesVisibility()
  drawOverlays()
  try { window.localStorage.setItem(LAYERS_KEY, JSON.stringify(layerVisibility)) } catch { /* noop */ }
})

function ema(values, period) {
  const k = 2 / (period + 1)
  const out = []
  let prev = null
  values.forEach((v, i) => {
    if (i < period - 1) {
      out.push(null)
      return
    }
    if (prev === null) {
      const seed = values.slice(0, period).reduce((a, b) => a + b, 0) / period
      prev = seed
    } else {
      prev = v * k + prev * (1 - k)
    }
    out.push(prev)
  })
  return out
}

function buildChart() {
  chart = createChart(container.value, {
    // Let the library track the container itself: creating the chart before the
    // parent column has laid out used to leave a 0-width canvas behind.
    autoSize: true,
    layout: {
      background: { color: 'transparent' },
      textColor: '#8b98a9',
      fontFamily: 'JetBrains Mono, ui-monospace, monospace',
      fontSize: 11,
    },
    grid: { vertLines: { color: 'rgba(38,51,63,0.45)' }, horzLines: { color: 'rgba(38,51,63,0.45)' } },
    rightPriceScale: { borderColor: '#1a2331', scaleMargins: { top: 0.12, bottom: 0.12 } },
    timeScale: {
      borderColor: '#1a2331', timeVisible: true, secondsVisible: false,
      barSpacing: spacing.value, minBarSpacing: 2, rightOffset: chartShift.value ? 8 : 1,
      rightBarStaysOnScroll: true,
      tickMarkFormatter: (time) => formatServerClock(time),
    },
    crosshair: {
      mode: 0,
      vertLine: { color: 'rgba(245,181,65,0.5)', labelBackgroundColor: '#b97c12' },
      horzLine: { color: 'rgba(245,181,65,0.5)', labelBackgroundColor: '#b97c12' },
    },
    handleScale: { axisPressedMouseMove: true },
  })
  candleSeries = chart.addCandlestickSeries({
    upColor: '#34d399',
    downColor: '#f87171',
    wickUpColor: 'rgba(52,211,153,0.65)',
    wickDownColor: 'rgba(248,113,113,0.65)',
    borderVisible: false,
    priceLineVisible: true,
    priceLineColor: 'rgba(245,181,65,0.6)',
  })
  const line = (color, width = 1) =>
    chart.addLineSeries({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
  ema20 = line('rgba(245,181,65,0.85)', 1)
  ema50 = line('rgba(96,165,250,0.8)', 1)
  ema200 = line('rgba(167,139,250,0.8)', 1)
  syncSeriesVisibility()
  chart.timeScale().subscribeVisibleLogicalRangeChange(syncViewport)
  resizeObs = new ResizeObserver(() => {
    if (!chart || !container.value) return
    const { clientWidth, clientHeight } = container.value
    if (clientWidth > 0 && clientHeight > 0) {
      chart.applyOptions({ width: clientWidth, height: clientHeight })
      if (autoScroll.value && bars.value) goLatest()
      syncViewport()
    }
  })
  resizeObs.observe(container.value)
}

const lastBarText = computed(() => {
  if (!lastBar.value) return '—'
  const d = new Date((lastBar.value + displayOffsetSeconds.value) * 1000)
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
})

async function retry() {
  error.value = ''
  if (!chart) buildChart()
  await load()
}

async function load({ silent = false } = {}) {
  if (!candleSeries) return
  const requestId = ++candleLoadRequestId
  const requestedSymbol = state.symbol
  const requestedTimeframe = state.timeframe
  const requestedRange = state.range
  const previousRange = chart.timeScale().getVisibleRange()
  const previousViewKey = loadedViewKey
  if (!silent) {
    loading.value = true
    error.value = ''
  }
  try {
    const data = await api.get(
      `/api/market/candles?symbol=${encodeURIComponent(requestedSymbol)}&timeframe=${requestedTimeframe}&limit=${requestedRange}`,
    )
    if (requestId !== candleLoadRequestId) return
    error.value = ''
    const raw = Array.isArray(data.candles) ? data.candles : []
    const nextViewKey = `${data.feed || 'feed'}:${data.symbol || requestedSymbol}:${requestedTimeframe}`
    displayBasis.value = data.time?.display_basis || 'utc'
    displayOffsetSeconds.value = displayBasis.value === 'broker_server'
      ? Number(data.time?.server_utc_offset_seconds || 0) : 0
    // lightweight-charts demands strictly ascending, unique timestamps.
    const seen = new Set()
    const clean = raw
      .filter((c) => c && Number.isFinite(Number(c.t)))
      .sort((a, b) => a.t - b.t)
      .filter((c) => {
        const t = Number(c.t)
        if (seen.has(t)) return false
        seen.add(t)
        return true
      })
    const candles = clean.map((c) => ({ time: Number(c.t), open: c.o, high: c.h, low: c.l, close: c.c }))
    bars.value = candles.length
    lastBar.value = candles.length ? candles[candles.length - 1].time : null
    state.candles = clean
    candleSeries.setData(candles)
    const closes = candles.map((c) => c.close)
    const line = (series, period) => series.setData(
      candles.map((c, i) => ({ time: c.time, value: ema(closes, period)[i] }))
        .filter((p) => Number.isFinite(p.value)),
    )
    line(ema20, 20)
    line(ema50, 50)
    line(ema200, 200)
    priceDigits = Number.isInteger(data.spec?.digits) ? Math.min(8, Math.max(0, data.spec.digits)) : 2
    lastCandle = candles[candles.length - 1] || null
    chart.timeScale().applyOptions({
      barSpacing: spacing.value, rightOffset: chartShift.value ? 8 : 1,
    })
    const firstTime = candles[0]?.time
    const lastTime = candles.at(-1)?.time
    let storedRange = null
    try {
      storedRange = JSON.parse(localStorage.getItem(`${VIEW_PREFS_KEY}:${nextViewKey}`) || 'null')
    } catch { /* ignore invalid saved viewport */ }
    if (autoScroll.value) {
      goLatest()
    } else if (previousViewKey === nextViewKey && validTimeRange(previousRange, firstTime, lastTime)) {
      chart.timeScale().setVisibleRange(previousRange)
    } else if (validTimeRange(storedRange, firstTime, lastTime)) {
      chart.timeScale().setVisibleRange(storedRange)
    } else {
      chart.timeScale().fitContent()
    }
    loadedViewKey = nextViewKey
    syncViewport()
    drawOverlays()
  } catch (err) {
    if (requestId === candleLoadRequestId) {
      error.value = !silent || bars.value === 0 ? String((err && err.message) || err) : ''
      console.error('[PriceChart] load failed', err)
    }
  } finally {
    if (requestId === candleLoadRequestId) loading.value = false
  }
}

function refreshAfterRecovery() {
  if (recoveryRefreshTimer) clearTimeout(recoveryRefreshTimer)
  recoveryRefreshTimer = setTimeout(() => {
    recoveryRefreshTimer = null
    load({ silent: true })
  }, 150)
}

function clearLines() {
  priceLines.forEach(({ series, line }) => {
    try {
      series.removePriceLine(line)
    } catch {
      /* noop */
    }
  })
  priceLines = []
}

function addLine(price, color, title, style = 2, width = 1) {
  if (!price || !Number.isFinite(Number(price))) return
  const line = candleSeries.createPriceLine({
    price: Number(price),
    color,
    lineWidth: width,
    lineStyle: style,
    axisLabelVisible: true,
    title,
  })
  priceLines.push({ series: candleSeries, line })
}

function drawShortMarkers() {
  const canvas = segmentCanvas.value
  if (!canvas || !container.value || !candleSeries) return
  const width = container.value.clientWidth
  const height = container.value.clientHeight
  const ratio = Math.max(1, window.devicePixelRatio || 1)
  if (width < 1 || height < 1) return
  canvas.width = Math.round(width * ratio)
  canvas.height = Math.round(height * ratio)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
  ctx.clearRect(0, 0, width, height)
  const span = shortMarkerSpan(width)
  if (!span) return
  for (const marker of shortMarkers) {
    const y = candleSeries.priceToCoordinate(marker.price)
    if (!Number.isFinite(y) || y < 1 || y > height - 1) continue
    ctx.save()
    ctx.strokeStyle = marker.color
    ctx.fillStyle = marker.color
    ctx.lineWidth = marker.emphasis ? 2 : 1.5
    ctx.setLineDash(marker.dashed ? [5, 3] : [])
    ctx.beginPath()
    ctx.moveTo(span.left, y)
    ctx.lineTo(span.right, y)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.font = '10px ui-monospace, monospace'
    const label = `${marker.label} ${Number(marker.price).toFixed(priceDigits)}`
    const labelWidth = ctx.measureText(label).width + 8
    const labelLeft = Math.max(span.left, span.right - labelWidth)
    ctx.globalAlpha = 0.9
    ctx.fillRect(labelLeft, y - 11, span.right - labelLeft, 12)
    ctx.globalAlpha = 1
    ctx.fillStyle = '#071018'
    ctx.fillText(label, labelLeft + 4, y - 2)
    ctx.restore()
  }
}

function drawOverlays() {
  if (!candleSeries) return
  clearLines()
  shortMarkers = []
  const signal = state.live?.signal
  const analysis = state.live?.analysis
  const plan = signal?.plan
  if (layerVisibility.plan && plan && ['BUY', 'SELL', 'WAIT'].includes(signal.action)) {
    if (matchesChartSymbol(signal.symbol, state.symbol)) {
      if (plan.entry > 0) shortMarkers.push({ price: plan.entry, color: 'rgba(245,181,65,0.95)', label: 'ENTRY', emphasis: true })
      if (plan.sl > 0) shortMarkers.push({ price: plan.sl, color: 'rgba(248,113,113,0.95)', label: 'SL', dashed: true })
      if (plan.tp1 > 0) shortMarkers.push({ price: plan.tp1, color: 'rgba(52,211,153,0.9)', label: 'TP1', dashed: true })
    }
  }
  if (layerVisibility.sr && analysis) {
    ;(analysis.resistances || []).slice(0, 2).forEach((z) =>
      addLine(z.mid, 'rgba(248,113,113,0.35)', `R ${z.quality[0].toUpperCase()}`, 3),
    )
    ;(analysis.supports || []).slice(0, 2).forEach((z) =>
      addLine(z.mid, 'rgba(52,211,153,0.35)', `S ${z.quality[0].toUpperCase()}`, 3),
    )
  }
  if (layerVisibility.flip) {
    ;(analysis?.sr_flips || []).slice(0, 4).forEach((event) => {
      const rising = event.direction === 'resistance_to_support'
      addLine(event.level, rising ? 'rgba(52,211,153,0.75)' : 'rgba(248,113,113,0.75)',
        rising ? 'Flip R→S' : 'Flip S→R', 2, 2)
    })
  }
  if (layerVisibility.fib && analysis?.fibonacci_band) {
    const fib = analysis.fibonacci_band
    addLine(fib.level_50, 'rgba(245,181,65,0.65)', 'Fib 50%', 3)
    addLine(fib.level_618, 'rgba(245,181,65,0.85)', 'Fib 61.8%', 3, 2)
  }
  if (layerVisibility.structure) {
    ;(analysis?.structure || []).filter((event) => event.confirmed).slice(-3).forEach((event) =>
      addLine(event.level, 'rgba(167,139,250,0.65)', event.kind, 3),
    )
  }
  if (layerVisibility.positions) {
    positions.value.filter(p => matchesChartSymbol(p.symbol, state.symbol)).forEach((p) => {
      const ticket = String(p.ticket).slice(-6)
      if (p.entry > 0) shortMarkers.push({ price: p.entry, color: 'rgba(96,165,250,0.9)', label: `#${ticket} IN` })
      if (p.sl > 0) shortMarkers.push({ price: p.sl, color: 'rgba(248,113,113,0.95)', label: `#${ticket} SL`, dashed: true })
      if (p.tp > 0) shortMarkers.push({ price: p.tp, color: 'rgba(52,211,153,0.95)', label: `#${ticket} TP`, dashed: true })
    })
  }
  drawShortMarkers()
}

function updateLast() {
  const tick = state.live?.ticker
  if (!canApplyLiveQuote(tick, state.live?.ticker_stale, state.serverUnreachable) || !lastCandle) return
  const seconds = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 }[state.timeframe] || 300
  const bucket = Math.floor(tick.t / seconds) * seconds
  const price = Number(tick.last)
  if (!Number.isFinite(bucket) || !Number.isFinite(price) || price <= 0 || bucket < lastCandle.time) return
  if (bucket > lastCandle.time) {
    lastCandle = { time: bucket, open: price, high: price, low: price, close: price }
    candleSeries.update(lastCandle)
    bars.value = nextBarCount(bars.value)
    if (autoScroll.value) goLatest()
  } else {
    lastCandle = {
      ...lastCandle,
      high: Math.max(lastCandle.high, price),
      low: Math.min(lastCandle.low, price),
      close: price,
    }
    candleSeries.update(lastCandle)
  }
  drawShortMarkers()
}

watch(() => [state.symbol, state.timeframe, state.range], () => load())
watch([
  () => state.connected,
  () => state.serverUnreachable,
  () => state.live?.ticker_stale,
  () => Boolean(state.live?.ticker),
], ([connected, serverUnreachable, tickerStale, hasTick],
  [wasConnected, wasServerUnreachable, wasTickerStale, hadTick]) => {
  if (needsCandleReloadOnRecovery(
    { connected: wasConnected, serverUnreachable: wasServerUnreachable,
      tickerStale: wasTickerStale, hasTick: hadTick },
    { connected, serverUnreachable, tickerStale, hasTick },
  )) refreshAfterRecovery()
})
watch(() => state.live?.version, () => {
  updateLast()
  drawOverlays()
})
watch(() => state.live?.ticker?.last, updateLast)
watch(positions, drawOverlays)

onMounted(async () => {
  try {
    buildChart()
  } catch (err) {
    error.value = `สร้างกราฟไม่สำเร็จ: ${(err && err.message) || err}`
    console.error('[PriceChart] build failed', err)
    return
  }
  await load()
})
onBeforeUnmount(() => {
  resizeObs?.disconnect()
  if (viewportFrame) cancelAnimationFrame(viewportFrame)
  if (markerFrame) cancelAnimationFrame(markerFrame)
  if (recoveryRefreshTimer) clearTimeout(recoveryRefreshTimer)
  clearTimeout(viewportSaveTimer)
  chart?.timeScale().unsubscribeVisibleLogicalRangeChange(syncViewport)
  chart?.remove()
  chart = null
})

// The chip used to be a two-way choice (simulated / MT5 LIVE), so a replayed feed
// — imported candles walking through the live pipeline — was labelled "MT5 LIVE".
const FEED_LABELS = {
  simulated: 'SIMULATED FEED',
  replay: 'REPLAY FEED',
  mt5: 'MT5 LIVE',
  'mt5-live': 'MT5 LIVE',
}
const feedIsStale = computed(() => state.serverUnreachable || state.live?.ticker_stale === true || !state.live?.ticker)
const feedLabel = computed(() => {
  const source = FEED_LABELS[state.live?.feed] || (state.live?.feed ? String(state.live.feed).toUpperCase() : 'FEED —')
  return feedIsStale.value ? `STALE · ${source}` : source
})
const feedWarn = computed(() => feedIsStale.value || (state.live?.feed !== 'mt5' && state.live?.feed !== 'mt5-live'))
const feedTitle = computed(() => {
  if (state.serverUnreachable) return 'ติดต่อ API ไม่ได้; กราฟเป็นข้อมูลล่าสุดที่มี ไม่ใช่ราคาสด'
  if (state.live?.ticker_stale === true) return 'ราคา tick เก่า; หยุดอัปเดตแท่งจนกว่าจะได้รับ quote ใหม่'
  if (!state.live?.ticker) return 'ยังไม่มี quote ปัจจุบัน; กราฟอาจเป็นข้อมูลย้อนหลัง'
  const f = state.live?.feed
  if (f === 'replay') return 'ราคามาจากไฟล์ที่นำเข้า (replay) — ไม่ใช่ tick data จริง และไม่ใช่ราคาสดจากโบรกเกอร์'
  if (f === 'simulated') return 'ราคาจากตัวจำลอง — ห้ามใช้ตัดสินใจกับเงินจริง'
  return 'ราคาจากเทอร์มินัล MT5'
})
</script>
