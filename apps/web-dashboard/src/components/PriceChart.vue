<template>
  <div ref="chartHost" class="relative flex flex-col bg-ink-900" :class="fullscreen ? 'h-screen p-2' : ''" tabindex="0" @keydown="chartKeydown">
    <div class="flex flex-wrap items-center gap-1.5 border-b border-ink-700/60 px-2 py-1 text-[11px]">
      <label for="chart-account" class="text-muted" title="แหล่งข้อมูลกราฟ"><ToolIcon name="chart" /><span class="sr-only">แหล่งข้อมูลกราฟ</span></label>
      <select id="chart-account" v-model="selectedAccount" class="input max-w-[160px] py-1 text-[11px]" @change="load">
        <option value="">ตลาดกลาง</option>
        <option v-for="account in marketAccounts" :key="account.id" :value="account.id">
          {{ account.label }} · {{ account.account_type.toUpperCase() }} · {{ account.market_connected ? 'เชื่อมต่อแล้ว' : 'รอเชื่อม MT5' }}
        </option>
      </select>
      <RouterLink to="/brokers" class="tool-btn" title="ผูกบัญชี / จัดการโบรกเกอร์" aria-label="ผูกบัญชี / จัดการโบรกเกอร์"><ToolIcon name="link" /></RouterLink>
      <span v-if="contextError" role="status" class="text-amber-200" title="โหลดสถานะบัญชีไม่ได้ · ยังดูกราฟตลาดกลางได้" aria-label="โหลดสถานะบัญชีไม่ได้"><ToolIcon name="alert" /></span>
      <span class="text-muted" :title="!marketAccounts.length ? 'ยังไม่ผูกบัญชี · ดูกราฟอย่างเดียว' : 'การเลือกกราฟไม่เปิดสิทธิ์ซื้อขาย'" aria-label="กราฟอ่านอย่างเดียว"><ToolIcon name="lock" /></span>
      <span class="mx-1 h-4 border-l border-ink-700" aria-hidden="true"></span>
      <button v-for="item in layerChoices" :key="item.key" type="button"
              class="rounded border px-2 py-1 text-[10px] transition-colors"
              :class="layerUnavailable(item.key) ? 'cursor-not-allowed border-ink-700 text-muted opacity-40' : layerVisibility[item.key] ? 'border-gold/50 bg-gold/10 text-gold' : 'border-ink-700 text-muted'"
              :disabled="layerUnavailable(item.key)" :aria-pressed="!layerUnavailable(item.key) && layerVisibility[item.key]"
              :title="layerDisabledReason(item.key) || 'เปิด/ปิดเฉพาะการแสดงผล ' + item.label" :aria-label="'เปิด/ปิด ' + item.label"
              @click="toggleLayer(item.key)">
        {{ item.short || item.label }}
      </button>
      <span v-if="quoteWarning" role="status" class="flex items-center gap-1 text-amber-200" :title="quoteWarning" :aria-label="quoteWarning"><ToolIcon name="alert" />{{ quoteWarning.startsWith('เวลา MT5') ? 'MT5 ≠ UTC' : chartFeed === 'simulated' ? 'SIMULATED' : chartFeed === 'replay' ? 'REPLAY' : 'ราคาไม่สด' }}</span>
    </div>
    <div class="flex flex-wrap items-center gap-1 border-b border-ink-700/60 px-2 py-1 text-[11px]" aria-label="ควบคุมกราฟ">
      <TimeframePicker />
      <span class="mx-1 h-4 border-l border-ink-700" aria-hidden="true"></span>
      <button class="tool-btn" :disabled="!bars || loading" aria-label="ซูมออก" title="ซูมออก (-)" @click="zoom(-1)"><ToolIcon name="zoomOut" /></button>
      <button class="tool-btn" :disabled="!bars || loading" aria-label="ซูมเข้า" title="ซูมเข้า (+)" @click="zoom(1)"><ToolIcon name="zoomIn" /></button>
      <label class="flex items-center gap-1 text-muted" title="ความกว้างต่อแท่ง (px)"><ToolIcon name="width" />
        <input aria-label="ความกว้างต่อแท่ง หน่วยพิกเซล" class="input w-14 py-1 text-[11px]" type="number" min="2" max="48" :value="spacing.toFixed(1)" @change="setSpacing($event.target.value)" />
      </label>
      <button class="tool-btn" :aria-pressed="autoScroll" aria-label="เลื่อนตามราคาล่าสุดอัตโนมัติ" title="Auto scroll · เลื่อนตามราคาล่าสุด" @click="toggleAutoScroll"><ToolIcon name="follow" /></button>
      <button class="tool-btn" :aria-pressed="chartShift" aria-label="เว้นพื้นที่ท้ายกราฟ" title="Chart shift · เว้นพื้นที่ท้ายกราฟ" @click="toggleShift"><ToolIcon name="shift" /></button>
      <button class="tool-btn" :disabled="!bars || loading" title="กลับแท่งล่าสุด (End)" aria-label="กลับแท่งล่าสุด" @click="goLatest"><ToolIcon name="latest" /></button>
      <button class="tool-btn" :disabled="!bars || loading" title="แสดงข้อมูลทั้งหมดที่โหลด" aria-label="ดูกราฟทั้งหมด" @click="fitAll"><ToolIcon name="fit" /></button>
      <button class="tool-btn w-10 text-[10px] font-semibold" title="มุมมอง MT5 · M1 · กว้าง 16px · สูง 580px" aria-label="มุมมอง MT5 M1" @click="mt5View">MT5</button>
      <button class="tool-btn" :aria-pressed="fullscreen" :title="fullscreen ? 'ออกเต็มจอ' : 'เต็มจอ'" :aria-label="fullscreen ? 'ออกเต็มจอ' : 'เต็มจอ'" @click="toggleFullscreen"><ToolIcon :name="fullscreen ? 'collapse' : 'fullscreen'" /></button>
      <button class="tool-btn" title="คืนสเกลราคาอัตโนมัติ" aria-label="สเกลราคาอัตโนมัติ" @click="resetPriceScale"><ToolIcon name="scale" /></button>
    </div>
    <div class="relative flex flex-wrap items-center gap-1.5 px-2 py-1 text-[10px] text-muted">
      <ToolIcon name="database" />
      <span>{{ visibleSummary }}</span>
      <span v-if="visiblePrices">· ราคา {{ visiblePrices }}</span>
      <span v-if="fixedPriceRange" title="ตรึงช่วงราคา" aria-label="ตรึงช่วงราคา"><ToolIcon name="lock" /></span>
      <span v-if="layerNote" role="status" class="text-amber-200">{{ layerNote }}</span>
      <RouterLink v-if="chartFeed.startsWith('mt5-') && !chartPositions.available && ['plan','positions'].includes(selectedLayerKey)" to="/brokers" class="text-gold">ผูก terminal →</RouterLink>
      <span v-if="overlayError" role="status" class="text-amber-200">{{ overlayError }}</span>
    <details class="ml-auto text-[11px] text-muted">
      <summary class="inline-flex cursor-pointer list-none items-center gap-1 rounded p-1 hover:bg-ink-800" title="ตั้งช่วงเวลา ช่วงราคา และความสูงกราฟ" aria-label="ตั้งช่วงเวลา ช่วงราคา และความสูงกราฟ"><ToolIcon name="sliders" /><span class="sr-only">ตั้งค่าช่วงกราฟ</span></summary>
      <div class="absolute inset-x-0 top-full z-20 rounded-b-lg border border-ink-700 bg-ink-900 p-3 shadow-xl">
      <div class="flex flex-wrap items-end gap-2">
        <label>สูง (px)<input v-model.number="chartHeight" aria-label="ความสูงกราฟ หน่วยพิกเซล" type="number" min="300" max="1000" step="20" class="input block w-20 py-1" @change="saveViewPrefs" /></label>
        <label>เริ่ม (เวลาแท่ง)<input v-model="timeFrom" type="datetime-local" class="input block py-1" /></label>
        <label>ถึง (เวลาแท่ง)<input v-model="timeTo" type="datetime-local" class="input block py-1" /></label>
        <button class="btn px-2 py-1" :disabled="!bars || loading" @click="applyTimeRange">แสดงช่วงเวลา</button>
        <label>ราคาต่ำสุด<input v-model="priceMin" type="number" step="any" class="input block w-24 py-1" /></label>
        <label>ราคาสูงสุด<input v-model="priceMax" type="number" step="any" class="input block w-24 py-1" /></label>
        <button class="btn px-2 py-1" :disabled="!bars || loading" :aria-pressed="Boolean(fixedPriceRange)" @click="applyFixedPrice">ตรึงช่วงราคา</button>
        <span>ใช้เวลาแท่งจาก source เดียวกับแกนล่าง · ช่วงที่เลือกต้องอยู่ในข้อมูลที่โหลด</span>
      </div>
      <p v-if="viewError" role="alert" class="pb-2 text-amber-200">{{ viewError }}</p>
      </div>
    </details>
    </div>
    <div class="relative min-h-0" :class="fullscreen ? 'flex-1' : ''" :style="fullscreen ? {} : { height: `${Math.min(1000, Math.max(300, Number(chartHeight) || 580))}px` }">
    <div ref="container" class="h-full w-full" @pointerdown="startChartDrag" @pointermove="moveChartDrag" @pointerup="endChartDrag" @pointercancel="endChartDrag" @pointerleave="endChartDrag"></div>
    <div class="pointer-events-none absolute left-3 top-2 flex flex-wrap items-center gap-1.5">
      <span class="chip chip-gold">{{ chartSymbol || state.symbol }} · {{ state.timeframe }}</span>
      <span class="chip" :class="feedWarn ? 'chip-warn' : ''" :title="feedTitle">{{ feedLabel }}</span>
      <span v-if="chartFeed !== 'mt5-live' && state.live?.analysis?.regime" class="chip">{{ state.live.analysis.regime.regime.replace('_',' ') }}</span>
      <span v-if="chartFeed === 'mt5-live' && chartOverlays?.available" class="chip" title="เครื่องมือวิเคราะห์จากแท่งปิดของ MT5 สัญลักษณ์และ timeframe เดียวกับกราฟ" aria-label="เครื่องมือจากข้อมูล MT5 เดียวกับกราฟ"><ToolIcon name="chart" /></span>
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
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { createChart } from 'lightweight-charts'
import { api } from '../lib/api'
import { positions, setTimeframe, state } from '../lib/store'
import { latestLogicalRange, nextBarSpacing, validPriceRange } from '../lib/chartViewport'
import { timeframeSeconds } from '../lib/chartTimeframes'
import TimeframePicker from './TimeframePicker.vue'
import ToolIcon from './ToolIcon.vue'
import { singleFlight } from '../lib/singleFlight'

const container = ref(null)
const chartHost = ref(null)
const loading = ref(false)
const error = ref('')
const bars = ref(0)
const lastBar = ref(null)
const chartFeed = ref('')
const chartSymbol = ref('')
const chartBrokerId = ref('')
const chartOverlays = ref(null)
const overlayError = ref('')
const selectedLayerKey = ref('')
const chartPositions = ref({ available: false, positions: [], reason: 'ผูก terminal ในหน้า Brokers เพื่อดูไม้จริง' })
const layerNote = computed(() => {
  if (chartFeed.value.startsWith('mt5-') && ['plan', 'positions'].includes(selectedLayerKey.value)) {
    const data = chartPositions.value
    if (!data.available || !data.positions.length) return data.reason || 'ไม่มีไม้เปิดของสัญลักษณ์นี้'
    if (selectedLayerKey.value === 'plan' && !data.positions.some(position => position.sl > 0 || position.tp > 0)) return 'ไม้จริงยังไม่ได้ตั้ง SL/TP ใน MT5'
    return ''
  }
  if (!chartFeed.value.startsWith('mt5-') || !chartOverlays.value?.available || !selectedLayerKey.value) return ''
  const data = chartOverlays.value
  const messages = {
    sr: !(data.supports?.length || data.resistances?.length) ? 'ยังไม่พบ S/R ที่ยืนยันในช่วงแท่งนี้' : '',
    flip: !data.sr_flips?.length ? 'ยังไม่พบ FLIP ที่ยืนยันในช่วงแท่งนี้' : '',
    fib: !data.fibonacci_band ? 'ยังไม่มีคู่ swing ที่ยืนยันสำหรับ FIB' : '',
    structure: !data.structure?.length ? 'ยังไม่พบ BOS/CHoCH ที่ยืนยันในช่วงแท่งนี้' : '',
  }
  return layerVisibility[selectedLayerKey.value] ? messages[selectedLayerKey.value] || '' : ''
})
const quoteWarning = ref('')
function showFreshness(data) {
  const freshness = data?.freshness
  quoteWarning.value = freshness?.clock_issue === 'future_timestamp'
    ? 'เวลา MT5 ต่างจากเวลา UTC ของเซิร์ฟเวอร์ · แสดงราคาและเวลาแท่งตาม MT5 โดยไม่ปรับเวลาเอง'
    : freshness?.stale ? 'ราคาล่าสุดเกิน 30 วินาที · กราฟนี้เป็นข้อมูลล่าสุดที่ได้รับ ไม่ใช่ราคาปัจจุบัน'
    : data?.feed === 'simulated' ? 'กราฟจำลอง · ขณะนี้ไม่มีข้อมูลตลาดจริงเชื่อมต่อ'
    : data?.feed === 'replay' ? 'กราฟย้อนหลังจากไฟล์ · ไม่ใช่ราคาตลาดปัจจุบัน' : ''
}
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
let historyTimer = null

const VIEW_PREFS_KEY = 'no7.chart.viewport.v1'
let savedPrefs = {}
try { savedPrefs = JSON.parse(localStorage.getItem(VIEW_PREFS_KEY) || '{}') || {} } catch { /* defaults */ }
const spacing = ref(Math.min(48, Math.max(2, Number(savedPrefs.spacing) || 16)))
const chartHeight = ref(Math.min(1000, Math.max(300, Number(savedPrefs.height) || 580)))
const autoScroll = ref(savedPrefs.autoScroll !== false)
const chartShift = ref(savedPrefs.chartShift !== false)
const fullscreen = ref(false)
const fixedPriceRange = ref(null)
const priceMin = ref('')
const priceMax = ref('')
const timeFrom = ref('')
const timeTo = ref('')
const viewError = ref('')
const visibleSummary = ref('')
const visiblePrices = ref('')
let loadedViewKey = ''
let viewportSaveTimer = null
let viewportFrame = null
let dragOrigin = null

function saveViewPrefs() {
  try {
    localStorage.setItem(VIEW_PREFS_KEY, JSON.stringify({ spacing: spacing.value,
      height: chartHeight.value, autoScroll: autoScroll.value, chartShift: chartShift.value }))
    const range = chart?.timeScale().getVisibleRange()
    if (range && loadedViewKey) localStorage.setItem(`${VIEW_PREFS_KEY}:${loadedViewKey}`, JSON.stringify(range))
  } catch { /* preferences are optional */ }
}

function syncViewport() {
  if (viewportFrame) cancelAnimationFrame(viewportFrame)
  viewportFrame = requestAnimationFrame(() => {
    if (!chart || !candleSeries) return
    spacing.value = chart.timeScale().options().barSpacing
    const logical = chart.timeScale().getVisibleLogicalRange()
    if (logical) {
      const count = Math.max(0, Math.min(bars.value - 1, Math.floor(logical.to)) - Math.max(0, Math.ceil(logical.from)) + 1)
      visibleSummary.value = `เห็น ${count} แท่ง · โหลด ${bars.value} แท่ง`
    }
    const upper = candleSeries.coordinateToPrice(0)
    const lower = candleSeries.coordinateToPrice(Math.max(0, container.value.clientHeight - 30))
    if (upper !== null && lower !== null) visiblePrices.value = `${Math.min(upper, lower).toFixed(priceDigits)} – ${Math.max(upper, lower).toFixed(priceDigits)}`
    clearTimeout(viewportSaveTimer)
    viewportSaveTimer = setTimeout(saveViewPrefs, 250)
  })
}

let priceDigits = 2
function latestRange() {
  const width = chart.timeScale().width() / spacing.value
  return latestLogicalRange(bars.value, width, chartShift.value ? width * 0.2 : 2)
}
function goLatest() {
  if (!chart || !bars.value) return
  autoScroll.value = true
  chart.timeScale().setVisibleLogicalRange(latestRange())
  saveViewPrefs()
}
function setSpacing(value) {
  const next = Number(value)
  if (!chart || !Number.isFinite(next)) return
  spacing.value = Math.min(48, Math.max(2, next))
  chart.timeScale().applyOptions({ barSpacing: spacing.value })
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
  if (autoScroll.value) goLatest()
  saveViewPrefs()
}
function fitAll() {
  if (!chart || !bars.value) return
  autoScroll.value = false
  chart.timeScale().fitContent()
  syncViewport()
}
function resetPriceScale() {
  fixedPriceRange.value = null
  viewError.value = ''
  chart?.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0.05, bottom: 0.1 } })
  chart?.applyOptions({ handleScale: { axisPressedMouseMove: { price: true, time: true } } })
  syncViewport()
}
function applyFixedPrice() {
  const range = validPriceRange(priceMin.value, priceMax.value)
  if (!range) { viewError.value = 'ราคาสูงสุดต้องมากกว่าราคาต่ำสุด'; return }
  fixedPriceRange.value = range
  viewError.value = ''
  chart?.priceScale('right').applyOptions({ autoScale: true, scaleMargins: { top: 0, bottom: 0 } })
  chart?.applyOptions({ handleScale: { axisPressedMouseMove: { price: false, time: true } } })
  syncViewport()
}
function applyTimeRange() {
  const from = Date.parse(`${timeFrom.value}Z`) / 1000
  const to = Date.parse(`${timeTo.value}Z`) / 1000
  const data = candleSeries?.data() || []
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) {
    viewError.value = 'เลือกเวลาเริ่มและสิ้นสุด โดยเวลาสิ้นสุดต้องอยู่หลังเวลาเริ่ม'; return
  }
  if (!data.length || from < data[0].time || to > data.at(-1).time) {
    viewError.value = 'ช่วงเวลานอกข้อมูลที่โหลด · เพิ่มจำนวนข้อมูลที่โหลดหรือเลือกช่วงที่อยู่บนกราฟ'; return
  }
  autoScroll.value = false
  chart.timeScale().setVisibleRange({ from, to })
  viewError.value = ''
  saveViewPrefs()
}
function mt5View() {
  setTimeframe('M1')
  chartHeight.value = 580
  layerVisibility.ema = false
  chartShift.value = true
  resetPriceScale()
  setSpacing(16)
  goLatest()
}
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement === chartHost.value) await document.exitFullscreen()
    else await chartHost.value.requestFullscreen()
  } catch { viewError.value = 'เบราว์เซอร์ไม่อนุญาตเต็มจอ'; }
}
function fullscreenChanged() {
  fullscreen.value = document.fullscreenElement === chartHost.value
  requestAnimationFrame(() => { if (autoScroll.value) goLatest(); syncViewport() })
}
function startChartDrag(event) { dragOrigin = { x: event.clientX, y: event.clientY } }
function moveChartDrag(event) {
  if (!dragOrigin || !event.buttons) return
  if (Math.abs(event.clientX - dragOrigin.x) > 4) {
    autoScroll.value = false
    saveViewPrefs()
  }
  syncViewport()
}
function endChartDrag() { dragOrigin = null; syncViewport() }
function chartKeydown(event) {
  if (event.target.closest('input, select, textarea, summary, button, a')) return
  if (event.key === '+' || event.key === '=') zoom(1)
  else if (event.key === '-') zoom(-1)
  else if (event.key === 'End') goLatest()
  else if (event.key === 'Home' && bars.value) {
    autoScroll.value = false
    const width = chart.timeScale().width() / spacing.value
    chart.timeScale().setVisibleLogicalRange({ from: 0, to: width })
  } else if (['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    autoScroll.value = false
    const scale = chart.timeScale()
    scale.scrollToPosition(scale.scrollPosition() + (event.key === 'ArrowLeft' ? -10 : 10), false)
  } else return
  event.preventDefault()
  syncViewport()
}

// UI preferences only: never write these switches into state.live or send an
// API request. Engine, risk controls and persisted trade decisions are unchanged.
const LAYERS_KEY = 'no7.chart.layers.v1'
function layerDisabledReason(key) {
  if (!chartFeed.value.startsWith('mt5-') || key === 'ema') return ''
  if (key === 'plan' || key === 'positions') return ''
  if (!chartOverlays.value?.available) return overlayError.value || 'กำลังเตรียมเครื่องมือจากแท่ง MT5'
  return ''
}
function layerUnavailable(key) { return Boolean(layerDisabledReason(key)) }
function toggleLayer(key) {
  if (layerUnavailable(key)) return
  layerVisibility[key] = !layerVisibility[key]
  selectedLayerKey.value = key
}
const layerChoices = [
  { key: 'ema', label: 'EMA' },
  { key: 'sr', label: 'S/R' },
  { key: 'flip', label: 'SR Flip', short: 'FLIP' },
  { key: 'fib', label: 'Fib 50–61.8', short: 'FIB' },
  { key: 'structure', label: 'BOS/CHoCH', short: 'BOS' },
  { key: 'plan', label: 'Entry/SL/TP', short: 'SL/TP' },
  { key: 'positions', label: 'ไม้เปิด', short: 'POS' },
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
    rightPriceScale: { borderColor: '#1a2331', minimumWidth: 76, mode: 0, scaleMargins: { top: 0.05, bottom: 0.1 } },
    timeScale: { borderColor: '#1a2331', timeVisible: true, secondsVisible: false,
      barSpacing: spacing.value, minBarSpacing: 2, rightOffset: 6, rightBarStaysOnScroll: true },
    crosshair: {
      mode: 0,
      vertLine: { color: 'rgba(245,181,65,0.5)', labelBackgroundColor: '#b97c12' },
      horzLine: { color: 'rgba(245,181,65,0.5)', labelBackgroundColor: '#b97c12' },
    },
    handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: { price: true, time: true }, axisDoubleClickReset: { price: true, time: true } },
    handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
  })
  candleSeries = chart.addCandlestickSeries({
    upColor: '#34d399',
    downColor: '#f87171',
    wickUpColor: 'rgba(52,211,153,0.65)',
    wickDownColor: 'rgba(248,113,113,0.65)',
    borderVisible: false,
    priceLineVisible: true,
    priceLineColor: 'rgba(245,181,65,0.6)',
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    autoscaleInfoProvider: original => fixedPriceRange.value ? { priceRange: fixedPriceRange.value } : original(),
  })
  const line = (color, width = 1) =>
    chart.addLineSeries({ color, lineWidth: width, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, autoscaleInfoProvider: () => null })
  ema20 = line('rgba(245,181,65,0.85)', 1)
  ema50 = line('rgba(96,165,250,0.8)', 1)
  ema200 = line('rgba(167,139,250,0.8)', 1)
  syncSeriesVisibility()
  chart.timeScale().subscribeVisibleLogicalRangeChange(syncViewport)
  resizeObs = new ResizeObserver(() => {
    if (!chart || !container.value) return
    const { clientWidth, clientHeight } = container.value
    if (clientWidth > 0 && clientHeight > 0) {
      chart.resize(clientWidth, clientHeight)
      if (autoScroll.value && bars.value) goLatest()
      syncViewport()
    }
  })
  resizeObs.observe(container.value)
}

const lastBarText = computed(() => {
  if (!lastBar.value) return '—'
  const d = new Date(lastBar.value * 1000)
  return chartFeed.value.startsWith('mt5-')
    ? `${d.toISOString().slice(0, 16).replace('T', ' ')} · เวลาแท่งจาก MT5`
    : d.toLocaleString('th-TH', { timeZoneName: 'short' })
})

async function retry() {
  error.value = ''
  if (!chart) buildChart()
  await load()
}

let loadVersion = 0
async function load(preserveView = false) {
  if (!candleSeries) return
  const previousRange = chart.timeScale().getVisibleRange()
  const previousKey = loadedViewKey
  const version = ++loadVersion
  const controller = new AbortController()
  const requestTimeout = setTimeout(() => controller.abort(), 8000)
  loading.value = true
  error.value = ''
  if (preserveView !== true) {
    chartFeed.value = ''
    chartSymbol.value = ''
    chartOverlays.value = null
    chartPositions.value = { available: false, positions: [], reason: 'กำลังตรวจบัญชีที่ผูกกับกราฟ' }
    overlayError.value = ''
  }
  try {
    const data = await api.get(
      `/api/market/candles?symbol=${encodeURIComponent(state.symbol)}&timeframe=${state.timeframe}&limit=${state.range}${accountQuery()}`,
      { signal: controller.signal },
    )
    if (version !== loadVersion) return
    chartFeed.value = data.feed || ''
    showFreshness(data)
    chartSymbol.value = data.source_symbol || data.symbol || state.symbol
    chartBrokerId.value = data.broker_id || ''
    const nextKey = `${data.feed}:${chartSymbol.value}:${state.timeframe}:${selectedAccount.value}`
    priceDigits = Number.isInteger(data.spec?.digits) ? data.spec.digits : 2
    candleSeries.applyOptions({ priceFormat: { type: 'price', precision: priceDigits,
      minMove: Number(data.spec?.point) || 10 ** -priceDigits } })
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
    const line = (series, period) => {
      const values = ema(closes, period)
      series.setData(candles.map((c, i) => ({ time: c.time, value: values[i] }))
        .filter((p) => Number.isFinite(p.value)))
    }
    line(ema20, 20)
    line(ema50, 50)
    line(ema200, 200)
    lastCandle = candles[candles.length - 1] || null
    if (chartFeed.value === 'mt5-live' && data.ticker) updateLast(data.ticker)
    loadedViewKey = nextKey
    let savedRange = previousKey === nextKey ? previousRange : null
    if (!savedRange) {
      try { savedRange = JSON.parse(localStorage.getItem(`${VIEW_PREFS_KEY}:${nextKey}`) || 'null') } catch { /* default */ }
    }
    if (autoScroll.value) goLatest()
    else if (savedRange && Number.isFinite(savedRange.from) && Number.isFinite(savedRange.to) && savedRange.to > savedRange.from) {
      chart.timeScale().setVisibleRange(savedRange)
    } else chart.timeScale().setVisibleLogicalRange(latestRange())
    syncViewport()
    drawOverlays()
  } catch (err) {
    if (version !== loadVersion) return
    if (err?.status === 503) chartFeed.value = 'mt5-disconnected'
    error.value = String((err && err.message) || err)
    console.error('[PriceChart] load failed', err)
  } finally {
    clearTimeout(requestTimeout)
    if (version === loadVersion) {
      loading.value = false
      if (chartFeed.value === 'mt5-live') { refreshChartOverlays(); refreshChartPositions() }
    }
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
  if (!chartFeed.value) return
  const native = chartFeed.value.startsWith('mt5-')
  const signal = native ? null : state.live?.signal
  const analysis = native ? chartOverlays.value : state.live?.analysis
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
  if (!native && layerVisibility.positions) {
    positions.value.forEach((p) => {
      addLine(p.entry, 'rgba(96,165,250,0.8)', `#${p.ticket}`, 1, 1)
      addLine(p.sl, 'rgba(248,113,113,0.6)', 'pos SL', 1, 1)
      addLine(p.tp, 'rgba(52,211,153,0.6)', 'pos TP', 1, 1)
    })
  }
  if (native && chartPositions.value.available) {
    for (const position of chartPositions.value.positions) {
      if (layerVisibility.positions) addLine(position.entry, 'rgba(96,165,250,0.8)', `#${position.ticket}`, 1, 1)
      if (layerVisibility.plan) {
        addLine(position.sl, 'rgba(248,113,113,0.8)', `SL #${position.ticket}`, 2)
        addLine(position.tp, 'rgba(52,211,153,0.8)', `TP #${position.ticket}`, 2)
      }
    }
  }
}

function updateLast(tick = state.live?.ticker) {
  if (!tick || !lastCandle) return
  const seconds = timeframeSeconds(state.timeframe)
  if (!seconds) return
  const bucket = Math.floor(tick.t / seconds) * seconds
  const price = Number(chartFeed.value === 'mt5-live' ? tick.bid : tick.last)
  if (!Number.isFinite(price) || bucket < lastCandle.time) return
  if (bucket > lastCandle.time) {
    lastCandle = { time: bucket, open: price, high: price, low: price, close: price }
    bars.value += 1
  } else {
    lastCandle = {
      ...lastCandle,
      high: Math.max(lastCandle.high, price),
      low: Math.min(lastCandle.low, price),
      close: price,
    }
  }
  candleSeries.update(lastCandle)
  lastBar.value = lastCandle.time
  if (autoScroll.value) goLatest()
  syncViewport()
}

watch(() => [state.symbol, state.timeframe, state.range], load)
watch(() => state.live?.version, () => {
  if (['simulated', 'simulate', 'replay'].includes(chartFeed.value)) updateLast()
  drawOverlays()
})
watch(() => state.live?.ticker?.last, (tick) => {
  if (['simulated', 'simulate', 'replay'].includes(chartFeed.value)) updateLast(state.live?.ticker)
})
watch(positions, drawOverlays)

const refreshChartPositions = singleFlight(async () => {
  if (!chart || !chartFeed.value.startsWith('mt5-')) return
  const version = loadVersion
  if (!selectedAccount.value) {
    chartPositions.value = { available: false, positions: [], reason: 'กราฟตลาดกลางไม่แสดงไม้ส่วนตัว · ผูก terminal ในหน้า Brokers ก่อน' }
    drawOverlays()
    return
  }
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 4000)
  try {
    const data = await api.get(`/api/market/positions?symbol=${encodeURIComponent(state.symbol)}${accountQuery()}`, { signal: controller.signal })
    if (version !== loadVersion) return
    if (data.available && (data.broker_id !== chartBrokerId.value || data.source_symbol !== chartSymbol.value)) throw new Error('บัญชีหรือสัญลักษณ์ไม่ตรงกับกราฟ')
    chartPositions.value = data
  } catch (error) {
    if (version === loadVersion) chartPositions.value = { available: false, positions: [], reason: error.message || 'ยืนยันสถานะไม้ไม่ได้' }
  } finally { clearTimeout(timeout); drawOverlays() }
})

const refreshChartOverlays = singleFlight(async () => {
  if (!chart || chartFeed.value !== 'mt5-live') return
  const version = loadVersion
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    const result = await api.get(`/api/market/overlays?symbol=${encodeURIComponent(state.symbol)}&timeframe=${encodeURIComponent(state.timeframe)}&limit=${state.range}${accountQuery()}`,
      { signal: controller.signal })
    if (version !== loadVersion) return
    if (result.broker_id !== chartBrokerId.value || result.source_symbol !== chartSymbol.value || result.timeframe !== state.timeframe) {
      throw new Error('ข้อมูลเครื่องมือไม่ตรงกับแหล่งกราฟ')
    }
    chartOverlays.value = result.analysis
    overlayError.value = result.analysis?.available ? '' : result.analysis?.reason || 'ข้อมูลยังไม่พอคำนวณเครื่องมือ'
    drawOverlays()
  } catch (error) {
    if (version === loadVersion) {
      chartOverlays.value = null
      overlayError.value = `เครื่องมือ MT5: ${error.message || 'โหลดข้อมูลไม่ได้'}`
      drawOverlays()
    }
  } finally { clearTimeout(timeout) }
})

const refreshChartQuote = singleFlight(async () => {
  if (loading.value || !chart) return
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 4000)
  try {
  const version = loadVersion
  const data = await api.get(`/api/market/ticker?symbol=${encodeURIComponent(state.symbol)}${accountQuery()}`, { silent: true, signal: controller.signal }).catch(() => null)
  if (version !== loadVersion || loading.value) return
  if (data?.feed) showFreshness(data)
  // Preserve MT5's own time for display. A freshly received future-dated quote
  // may be drawn, but the API keeps stale=true so it is never certified fresh.
  const brokerTimeOnly = data?.freshness?.clock_issue === 'future_timestamp' && data.transport_stale === false
  if (data?.feed === 'mt5-live' && data.tick && (data.stale === false || brokerTimeOnly)) {
    const reconnected = chartFeed.value !== 'mt5-live'
    chartFeed.value = 'mt5-live'
    if (reconnected) await load()
    updateLast(data.tick)
    refreshChartPositions()
    return
  }
  if (chartFeed.value === 'mt5-live') {
    chartFeed.value = 'mt5-disconnected'
    quoteWarning.value = 'MT5 ขาดการเชื่อมต่อ · คงกราฟล่าสุดไว้และหยุดอัปเดตราคา'
    chartPositions.value = { available: false, positions: [], reason: 'MT5 ขาดการเชื่อมต่อ · ยังยืนยันสถานะไม้ไม่ได้' }
    drawOverlays()
  }
  } finally { clearTimeout(timeout) }
})

onMounted(async () => {
  document.addEventListener('fullscreenchange', fullscreenChanged)
  try {
    buildChart()
  } catch (err) {
    error.value = `สร้างกราฟไม่สำเร็จ: ${(err && err.message) || err}`
    console.error('[PriceChart] build failed', err)
    return
  }
  await load()
  await refreshMarketContext()
  contextTimer = setInterval(() => { if (!document.hidden) refreshMarketContext() }, 10000)
  quoteTimer = setInterval(() => { if (!document.hidden) refreshChartQuote() }, 1000)
  historyTimer = setInterval(() => {
    if (!document.hidden && chartFeed.value === 'mt5-live' && !loading.value) load(true)
  }, 5000)
})
onBeforeUnmount(() => {
  saveViewPrefs()
  document.removeEventListener('fullscreenchange', fullscreenChanged)
  clearTimeout(viewportSaveTimer)
  if (viewportFrame) cancelAnimationFrame(viewportFrame)
  resizeObs?.disconnect()
  if (quoteTimer) clearInterval(quoteTimer)
  if (historyTimer) clearInterval(historyTimer)
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
