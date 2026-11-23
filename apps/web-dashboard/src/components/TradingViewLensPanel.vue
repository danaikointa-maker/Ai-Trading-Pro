<template>
  <details class="panel overflow-hidden">
    <summary class="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2.5">
      <span>
        <span class="panel-title">TradingView Lens · Shadow</span>
        <span class="ml-2 chip">อ่านอย่างเดียว</span>
      </span>
      <span class="chip" :class="error ? 'chip-warn' : 'chip-gold'">{{ status }}</span>
    </summary>
    <div class="border-t border-ink-700/70 px-3 py-2.5">
      <p class="mb-2 text-[10.5px] leading-relaxed text-muted">
        คะแนนจาก TradingView แยกจาก No7 และไม่มีสิทธิ์สั่งซื้อขาย · แสดงเฉพาะแท่งปิดที่รับเข้าแล้ว
      </p>
      <p v-if="error" class="text-[11px] text-amber-200">{{ error }}</p>
      <p v-else-if="!evidence.length" class="text-[11px] text-muted">ยังไม่มี packet ที่ผ่านการตรวจรับ</p>
      <div v-for="item in evidence.slice(0, 3)" :key="item.payload_sha256"
           class="mb-1.5 rounded-lg border border-ink-700 bg-ink-900/60 px-2.5 py-2 last:mb-0">
        <div class="flex flex-wrap items-center justify-between gap-2 text-[10.5px]">
          <span class="font-medium text-slate-200">{{ item.source_symbol }} → {{ item.mapped_symbol }} · {{ tfLabel(item.timeframe) }}</span>
          <span class="flex gap-1.5">
            <span class="chip" :class="item.freshness?.status === 'fresh' ? 'chip-up' : 'chip-warn'">{{ item.freshness?.status || 'ไม่ทราบความสด' }}</span>
            <span class="chip" :class="item.comparison?.status === 'exact_bar_match' ? 'chip-up' : 'chip-warn'">
              {{ item.comparison?.status === 'exact_bar_match' ? 'แท่งตรงกัน' : 'ยังจับคู่แท่งไม่ได้' }}
            </span>
          </span>
        </div>
        <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted">
          <span>แท่งปิด {{ timeLabel(item.bar_close_utc) }}</span>
          <span class="text-up">Lens L {{ item.long_score }}</span>
          <span class="text-down">Lens S {{ item.short_score }}</span>
          <span v-if="item.comparison?.status === 'exact_bar_match'">No7 {{ item.comparison.no7_action }} · {{ item.comparison.no7_score }}</span>
        </div>
      </div>
    </div>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state } from '../lib/store'

const evidence = ref([])
const error = ref('')
const busy = ref(false)
const status = computed(() => error.value ? 'ไม่พร้อม' : evidence.value.length ? 'Shadow' : 'รอข้อมูล')
let timer = null
let requestId = 0
let pending = false

function tfLabel(tf) {
  const labels = { '1': 'M1', '3': 'M3', '5': 'M5', '15': 'M15', '30': 'M30', '60': 'H1', '120': 'H2', '240': 'H4', D: 'D1', W: 'W1' }
  return labels[tf] || tf
}
function timeLabel(epoch) {
  return new Date(epoch * 1000).toLocaleString(undefined, {
    timeZone: 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    timeZoneName: 'short',
  })
}
async function refresh() {
  if (busy.value) {
    pending = true
    return
  }
  const current = ++requestId
  busy.value = true
  error.value = ''
  try {
    const q = new URLSearchParams({ symbol: state.symbol, timeframe: state.timeframe, limit: '10' })
    const result = await api.get(`/api/integrations/tradingview/ai-agent-lens/latest?${q}`, { silent: true })
    if (current === requestId) evidence.value = result?.evidence || []
  } catch (err) {
    if (current === requestId) error.value = err?.message || 'โหลดข้อมูล Shadow ไม่ได้'
  } finally {
    busy.value = false
    if (pending) {
      pending = false
      refresh()
    }
  }
}
watch(() => [state.symbol, state.timeframe], refresh)
onMounted(() => {
  refresh()
  timer = window.setInterval(refresh, 30000)
})
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })
</script>
