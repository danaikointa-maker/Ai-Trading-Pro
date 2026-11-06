<template>
  <div class="relative">
    <div ref="container" class="h-[380px] w-full sm:h-[440px]"></div>
    <div class="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-1.5">
      <span class="chip chip-gold">{{ state.symbol }} · {{ state.timeframe }}</span>
      <span class="chip">{{ state.live?.feed === 'simulated' ? 'SIMULATED FEED' : 'MT5 LIVE' }}</span>
      <span v-if="state.live?.analysis?.regime" class="chip">{{ state.live.analysis.regime.regime.replace('_',' ') }}</span>
    </div>
    <div v-if="loading" class="absolute inset-0 grid place-items-center bg-ink-900/40 text-[12px] text-muted">loading chart…</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'
import { api } from '../lib/api'
import { state } from '../lib/store'

const container = ref(null)
const loading = ref(false)
let chart = null
let candleSeries = null
let ema20 = null
let ema50 = null
let ema200 = null
let priceLines = []
let lastCandle = null
let resizeObs = null

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
  resizeObs = new ResizeObserver(() => {
    if (chart && container.value) chart.applyOptions({ width: container.value.clientWidth })
  })
  resizeObs.observe(container.value)
}

async function load() {
  if (!candleSeries) return
  loading.value = true
  try {
    const data = await api.get(
      `/api/market/candles?symbol=${encodeURIComponent(state.symbol)}&timeframe=${state.timeframe}&limit=${state.range}`,
    )
    const candles = data.candles.map((c) => ({ time: c.t, open: c.o, high: c.h, low: c.l, close: c.c }))
    state.candles = data.candles
    candleSeries.setData(candles)
    const closes = data.candles.map((c) => c.c)
    ema20.setData(data.candles.map((c, i) => ({ time: c.t, value: ema(closes, 20)[i] })).filter((p) => p.value))
    ema50.setData(data.candles.map((c, i) => ({ time: c.t, value: ema(closes, 50)[i] })).filter((p) => p.value))
    ema200.setData(data.candles.map((c, i) => ({ time: c.t, value: ema(closes, 200)[i] })).filter((p) => p.value))
    lastCandle = candles[candles.length - 1] || null
    chart.timeScale().fitContent()
    drawOverlays()
  } catch (err) {
    console.warn(err)
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
  const signal = state.live?.signal
  const analysis = state.live?.analysis
  const plan = signal?.plan
  if (plan && ['BUY', 'SELL', 'WAIT'].includes(signal.action)) {
    addLine(plan.entry, 'rgba(245,181,65,0.9)', 'entry', 0, 2)
    addLine(plan.sl, 'rgba(248,113,113,0.9)', 'SL', 2, 1)
    addLine(plan.tp1, 'rgba(52,211,153,0.7)', 'TP1', 2, 1)
    addLine(plan.tp2, 'rgba(52,211,153,0.55)', 'TP2', 2, 1)
    addLine(plan.tp3, 'rgba(52,211,153,0.4)', 'TP3', 2, 1)
  }
  if (analysis) {
    ;(analysis.resistances || []).slice(0, 2).forEach((z) =>
      addLine(z.mid, 'rgba(248,113,113,0.35)', `R ${z.quality[0].toUpperCase()}`, 3),
    )
    ;(analysis.supports || []).slice(0, 2).forEach((z) =>
      addLine(z.mid, 'rgba(52,211,153,0.35)', `S ${z.quality[0].toUpperCase()}`, 3),
    )
  }
  const positions = state.live?.positions || []
  positions.forEach((p) => {
    addLine(p.entry, 'rgba(96,165,250,0.8)', `#${p.ticket}`, 1, 1)
    addLine(p.sl, 'rgba(248,113,113,0.6)', 'pos SL', 1, 1)
    addLine(p.tp, 'rgba(52,211,153,0.6)', 'pos TP', 1, 1)
  })
}

function updateLast() {
  const tick = state.live?.ticker
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
  updateLast()
  drawOverlays()
})
watch(() => state.live?.ticker?.last, updateLast)

onMounted(async () => {
  buildChart()
  await load()
})
onBeforeUnmount(() => {
  resizeObs?.disconnect()
  chart?.remove()
  chart = null
})
</script>
