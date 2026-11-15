<template>
  <section class="rounded-lg border border-ink-700 p-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 class="text-xs font-semibold text-slate-200">ประวัติแท่งเทียนแยกตามไม้ · {{ trade.ticket }}</h3>
        <p class="mt-1 text-[10px] text-muted">M5 ก่อนเข้าไม้ตาม snapshot เดิม + หลังเข้าไม้ที่ระบบบันทึกไว้จริงเท่านั้น</p>
      </div>
      <div class="flex flex-wrap gap-1">
        <button v-for="layer in layers" :key="layer.key" type="button"
                class="btn py-1 text-[10px]" :aria-pressed="visible[layer.key]"
                @click="visible[layer.key] = !visible[layer.key]">
          {{ visible[layer.key] ? '✓' : '○' }} {{ layer.label }}
        </button>
      </div>
    </div>
    <div v-if="candles.length" ref="container" class="mt-3 h-[300px] w-full"></div>
    <p v-else class="mt-3 rounded border border-amber-600/40 p-3 text-xs text-amber-300">
      ไม่มีแท่งเทียนที่ระบบบันทึกสำหรับไม้นี้ จึงไม่ดึงกราฟปัจจุบันมาสวมเป็นประวัติ
    </p>
    <p v-if="candles.length" class="mt-2 text-[10px] text-muted">
      {{ beforeCandles.length }} แท่งก่อนเข้า · {{ afterCandles.length }} แท่งหลังเข้า (สีม่วง)
      · ข้อมูลล่าสุด {{ new Date((candles[candles.length - 1].t + 300) * 1000).toLocaleString() }}
      · ไม่เติมแท่งเทียนในช่วงที่ระบบไม่ได้สังเกต
    </p>
    <p v-if="afterCandles.length" class="mt-1 text-[10px] text-amber-300">
      แท่งหลังเข้าเป็นข้อมูล M5 ที่เห็นในรอบทำงาน ({{ feedLabels }}) ยังไม่ใช่หลักฐาน tick/deal จากโบรกเกอร์
      และยังไม่รับรองว่าครบทุกช่วงเวลาที่ถือไม้
    </p>
    <p class="mt-1 text-[10px] text-muted">การแสดง/ซ่อนทุกชั้นเป็นเพียงการตั้งค่าหน้าจอ ไม่มีการเรียก API สั่งออเดอร์</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'

const props = defineProps({
  trade: { type: Object, required: true },
  snapshot: { type: Object, default: null },
  analysis: { type: Object, default: null },
  postEntry: { type: Object, default: null },
})
const container = ref(null)
const layers = [
  { key: 'observed', label: 'แท่งหลังเข้า' },
  { key: 'plan', label: 'Entry/SL/TP' }, { key: 'zones', label: 'S/R' },
  { key: 'flip', label: 'SR Flip' }, { key: 'fib', label: 'Fib' },
  { key: 'structure', label: 'BOS/CHoCH' }, { key: 'actual', label: 'Fill/Exit' },
]
const visible = reactive({ observed: true, plan: true, zones: true, flip: true,
  fib: true, structure: false, actual: true })
const beforeCandles = computed(() => (props.analysis?.decision_candles || [])
  .filter((bar) => Number.isFinite(Number(bar.t)) && Number.isFinite(Number(bar.c)))
  .sort((a, b) => a.t - b.t)
  .filter((bar, index, arr) => index === 0 || bar.t !== arr[index - 1].t))
const afterCandles = computed(() => (props.postEntry?.bars || [])
  .filter((bar) => Number.isFinite(Number(bar.t)) && Number.isFinite(Number(bar.c)))
  .sort((a, b) => a.t - b.t)
  .filter((bar, index, arr) => index === 0 || bar.t !== arr[index - 1].t))
const feedLabels = computed(() => [...new Set(afterCandles.value.map((bar) => bar.feed_mode))].join(', '))
const afterTimes = computed(() => new Set(afterCandles.value.map((bar) => Number(bar.t))))
const candles = computed(() => [...beforeCandles.value, ...(visible.observed ? afterCandles.value : [])]
  .sort((a, b) => a.t - b.t)
  .filter((bar, index, arr) => index === 0 || bar.t !== arr[index - 1].t))

let chart = null
let series = null
let lines = []
let observer = null

function add(label, price, color) {
  if (!series || price === null || price === undefined || !Number.isFinite(Number(price)) || Number(price) <= 0) return
  lines.push(series.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle: 2,
    axisLabelVisible: true, title: label }))
}

function draw() {
  if (!series) return
  for (const line of lines) series.removePriceLine(line)
  lines = []
  const plan = props.snapshot?.plan
  const analysis = props.analysis
  if (visible.plan && plan) {
    add('Plan entry', plan.entry, '#fbbf24')
    add('Original SL', plan.sl, '#fb7185')
    ;['tp1', 'tp2', 'tp3'].forEach((key) => add(key.toUpperCase(), plan[key], '#34d399'))
  }
  if (visible.zones) {
    ;(analysis?.zones || []).slice(0, 4).forEach((zone) => {
      add(`${zone.kind} low`, zone.low, '#38bdf8')
      add(`${zone.kind} high`, zone.high, '#38bdf8')
    })
  }
  if (visible.flip) (analysis?.sr_flips || []).slice(0, 4).forEach((event) => add('SR flip', event.level, '#22d3ee'))
  if (visible.fib && analysis?.fibonacci_band) {
    add('Fib 50', analysis.fibonacci_band.level_50, '#f59e0b')
    add('Fib 61.8', analysis.fibonacci_band.level_618, '#eab308')
  }
  if (visible.structure) (analysis?.structure || []).filter((event) => event.confirmed).slice(-3)
    .forEach((event) => add(event.kind, event.level, '#c4b5fd'))
  if (visible.actual) {
    add('Filled entry', props.trade.entry, '#60a5fa')
    add('Exit', props.trade.exit, '#a78bfa')
  }
}

function render() {
  if (!container.value || !candles.value.length) return
  chart?.remove()
  chart = createChart(container.value, {
    autoSize: true,
    layout: { background: { color: 'transparent' }, textColor: '#94a3b8' },
    grid: { vertLines: { color: '#1e293b' }, horzLines: { color: '#1e293b' } },
    timeScale: { timeVisible: true },
  })
  series = chart.addCandlestickSeries({ upColor: '#34d399', downColor: '#f87171',
    wickUpColor: '#34d399', wickDownColor: '#f87171', borderVisible: false })
  series.setData(candles.value.map((bar) => ({ time: Number(bar.t),
    open: bar.o, high: bar.h, low: bar.l, close: bar.c,
    ...(visible.observed && afterTimes.value.has(Number(bar.t))
      ? { color: '#a78bfa', wickColor: '#c4b5fd' } : {}),
  })))
  chart.timeScale().fitContent()
  draw()
}

watch(visible, draw)
watch(() => [props.analysis, props.trade, props.snapshot, props.postEntry, visible.observed], () => {
  if (candles.value.length) render()
  else { chart?.remove(); chart = null; series = null; lines = [] }
}, { flush: 'post' })
onMounted(() => {
  render()
  if (typeof ResizeObserver !== 'undefined' && container.value) {
    observer = new ResizeObserver(() => chart?.applyOptions({ width: container.value?.clientWidth || 300 }))
    observer.observe(container.value)
  }
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.remove(); series = null; chart = null })
</script>
