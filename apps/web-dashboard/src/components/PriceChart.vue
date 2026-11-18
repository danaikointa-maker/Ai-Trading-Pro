<template>
  <div class="relative">
    <div class="flex flex-wrap items-center gap-2 border-b border-ink-700/60 px-3 py-2 text-[11px]">
      <label for="chart-account">แหล่งข้อมูลกราฟ</label>
      <select id="chart-account" v-model="selectedAccount" class="input w-auto py-1" @change="load">
        <option value="">ตลาดกลาง · ดูกราฟได้โดยไม่ผูกบัญชี</option>
        <option v-for="account in marketAccounts" :key="account.id" :value="account.id">
          {{ account.label }} · {{ account.account_type.toUpperCase() }} · {{ account.market_connected ? 'เชื่อมต่อแล้ว' : 'รอเชื่อม MT5' }}
        </option>
      </select>
      <RouterLink to="/brokers" class="text-gold">ผูกบัญชีโบรกเกอร์</RouterLink>
      <span v-if="contextError" class="text-amber-200">โหลดสถานะบัญชีไม่ได้ · ยังดูกราฟตลาดกลางได้</span>
      <span v-else-if="!marketAccounts.length" class="text-muted">ยังไม่ผูกบัญชี · ดูกราฟอย่างเดียว</span>
      <span class="text-muted">การเลือกกราฟไม่เปิดสิทธิ์ซื้อขาย</span>
    </div>
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
    <div ref="container" class="h-[380px] w-full sm:h-[440px]"></div>
    <div class="pointer-events-none absolute left-3 top-12 flex flex-wrap items-center gap-1.5">
      <span class="chip chip-gold">{{ chartSymbol || state.symbol }} · {{ state.timeframe }}</span>
      <span class="chip" :class="feedWarn ? 'chip-warn' : ''" :title="feedTitle">{{ feedLabel }}</span>
      <span v-if="chartFeed !== 'mt5-live' && state.live?.analysis?.regime" class="chip">{{ state.live.analysis.regime.regime.replace('_',' ') }}</span>
      <span v-if="chartFeed === 'mt5-live'" class="chip chip-warn" title="สัญญาณและสถานะบัญชียังมาจาก runtime อีกชุด; ซ่อนไว้จากกราฟ MT5 นี้">ซ่อน overlay จาก runtime</span>
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

const container = ref(null)
const loading = ref(false)
const error = ref('')
const bars = ref(0)
const lastBar = ref(null)
const chartFeed = ref('')
const chartSymbol = ref('')
const selectedAccount = ref('')
const marketAccounts = ref([])
const contextError = ref(false)
let contextTimer = null
function accountQuery() {
  return selectedAccount.value ? `&account_id=${encodeURIComponent(selectedAccount.value)}` : ''
}
async function refreshMarketContext() {
  try {
    const data = await api.get('/api/market/context', { silent: true })
    marketAccounts.value = data.accounts || []
    contextError.value = false
    // Prefer only verified account sessions; a saved record alone is not a connection.
    if (!selectedAccount.value && !userChoseSource) {
      const connected = marketAccounts.value.find(a => a.market_connected)
      if (connected) { selectedAccount.value = connected.id; await load() }
    }
  } catch { contextError.value = true }
}
let userChoseSource = false
watch(selectedAccount, () => { userChoseSource = true })
let chart = null
let candleSeries = null
let ema20 = null
let ema50 = null
let ema200 = null
let priceLines = []
let lastCandle = null
let resizeObs = null
let quoteTimer = null

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
    timeScale: { borderColor: '#1a2331', timeVisible: true, secondsVisible: false, rightOffset: 6 },
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
  resizeObs = new ResizeObserver(() => {
    if (!chart || !container.value) return
    const { clientWidth, clientHeight } = container.value
    if (clientWidth > 0 && clientHeight > 0) {
      chart.applyOptions({ width: clientWidth, height: clientHeight })
    }
  })
  resizeObs.observe(container.value)
}

const lastBarText = computed(() => {
  if (!lastBar.value) return '—'
  const d = new Date(lastBar.value * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

async function retry() {
  error.value = ''
  if (!chart) buildChart()
  await load()
}

async function load() {
  if (!candleSeries) return
  loading.value = true
  error.value = ''
  chartFeed.value = ''
  chartSymbol.value = ''
  try {
    const data = await api.get(
      `/api/market/candles?symbol=${encodeURIComponent(state.symbol)}&timeframe=${state.timeframe}&limit=${state.range}${accountQuery()}`,
    )
    chartFeed.value = data.feed || ''
    chartSymbol.value = data.source_symbol || data.symbol || state.symbol
    const raw = Array.isArray(data.candles) ? data.candles : []
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
    lastCandle = candles[candles.length - 1] || null
    chart.timeScale().fitContent()
    drawOverlays()
  } catch (err) {
    if (err?.status === 503) chartFeed.value = 'mt5-disconnected'
    error.value = String((err && err.message) || err)
    console.error('[PriceChart] load failed', err)
  } finally {
    loading.value = false
  }
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

function drawOverlays() {
  if (!candleSeries) return
  clearLines()
  // Runtime signals and positions may belong to a different feed/account. Keep
  // the actual MT5 chart clean until the whole analysis runtime uses that source.
  if (chartFeed.value === 'mt5-live') return
  const signal = state.live?.signal
  const analysis = state.live?.analysis
  const plan = signal?.plan
  if (layerVisibility.plan && plan && ['BUY', 'SELL', 'WAIT'].includes(signal.action)) {
    addLine(plan.entry, 'rgba(245,181,65,0.9)', 'entry', 0, 2)
    addLine(plan.sl, 'rgba(248,113,113,0.9)', 'SL', 2, 1)
    addLine(plan.tp1, 'rgba(52,211,153,0.7)', 'TP1', 2, 1)
    addLine(plan.tp2, 'rgba(52,211,153,0.55)', 'TP2', 2, 1)
    addLine(plan.tp3, 'rgba(52,211,153,0.4)', 'TP3', 2, 1)
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
    positions.value.forEach((p) => {
      addLine(p.entry, 'rgba(96,165,250,0.8)', `#${p.ticket}`, 1, 1)
      addLine(p.sl, 'rgba(248,113,113,0.6)', 'pos SL', 1, 1)
      addLine(p.tp, 'rgba(52,211,153,0.6)', 'pos TP', 1, 1)
    })
  }
}

function updateLast(tick = state.live?.ticker) {
  if (!tick || !lastCandle) return
  const seconds = { M1: 60, M5: 300, M15: 900, H1: 3600, H4: 14400 }[state.timeframe] || 300
  const bucket = Math.floor(tick.t / seconds) * seconds
  const price = Number(tick.last)
  if (bucket > lastCandle.time) {
    lastCandle = { time: bucket, open: price, high: price, low: price, close: price }
  } else {
    lastCandle = {
      ...lastCandle,
      high: Math.max(lastCandle.high, price),
      low: Math.min(lastCandle.low, price),
      close: price,
    }
  }
  candleSeries.update(lastCandle)
}

watch(() => [state.symbol, state.timeframe, state.range], load)
watch(() => state.live?.version, () => {
  if (chartFeed.value !== 'mt5-live') updateLast()
  drawOverlays()
})
watch(() => state.live?.ticker?.last, (tick) => {
  if (chartFeed.value !== 'mt5-live') updateLast(state.live?.ticker)
})
watch(positions, drawOverlays)

async function refreshChartQuote() {
  const data = await api.get(`/api/market/ticker?symbol=${encodeURIComponent(state.symbol)}${accountQuery()}`, { silent: true }).catch(() => null)
  if (data?.feed === 'mt5-live' && data.tick && data.stale === false) {
    const reconnected = chartFeed.value !== 'mt5-live'
    chartFeed.value = 'mt5-live'
    if (reconnected) await load()
    updateLast(data.tick)
    return
  }
  if (chartFeed.value === 'mt5-live') chartFeed.value = 'mt5-disconnected'
}

onMounted(async () => {
  try {
    buildChart()
  } catch (err) {
    error.value = `สร้างกราฟไม่สำเร็จ: ${(err && err.message) || err}`
    console.error('[PriceChart] build failed', err)
    return
  }
  await load()
  await refreshMarketContext()
  contextTimer = setInterval(refreshMarketContext, 10000)
  quoteTimer = setInterval(refreshChartQuote, 2000)
})
onBeforeUnmount(() => {
  resizeObs?.disconnect()
  if (quoteTimer) clearInterval(quoteTimer)
  if (contextTimer) clearInterval(contextTimer)
  chart?.remove()
  chart = null
})

// The chip used to be a two-way choice (simulated / MT5 LIVE), so a replayed feed
// — imported candles walking through the live pipeline — was labelled "MT5 LIVE".
const FEED_LABELS = {
  simulated: 'SIMULATED FEED',
  replay: 'REPLAY FEED',
  mt5: 'MT5 LIVE',
  'mt5-live': 'MT5 REAL · READ-ONLY',
  'mt5-disconnected': 'MT5 DISCONNECTED',
}
const displayedFeed = computed(() => chartFeed.value || state.live?.feed || '')
const feedLabel = computed(() => FEED_LABELS[displayedFeed.value] || (displayedFeed.value ? String(displayedFeed.value).toUpperCase() : 'FEED —'))
const feedWarn = computed(() => displayedFeed.value !== 'mt5' && displayedFeed.value !== 'mt5-live')
const feedTitle = computed(() => {
  const f = displayedFeed.value
  if (f === 'replay') return 'ราคามาจากไฟล์ที่นำเข้า (replay) — ไม่ใช่ tick data จริง และไม่ใช่ราคาสดจากโบรกเกอร์'
  if (f === 'simulated') return 'ราคาจากตัวจำลอง — ห้ามใช้ตัดสินใจกับเงินจริง'
  if (f === 'mt5-live') return 'กราฟและราคาอ่านจาก MT5 ที่ล็อกอินอยู่; หน้ากราฟนี้ไม่ส่งคำสั่งซื้อขาย'
  if (f === 'mt5-disconnected') return 'เลือก broker MT5 ไว้ แต่ terminal/bridge ยังไม่เชื่อมต่อ'
  return 'ราคาจากเทอร์มินัล MT5'
})
</script>
