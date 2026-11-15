<template>
  <div class="rounded-lg border border-ink-700 p-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 class="text-xs font-semibold text-slate-200">เส้นราคาแยกตามไม้ · {{ trade.ticket }}</h3>
        <p class="text-[10px] text-muted">แผนผังระดับราคาที่บันทึกไว้ ไม่ใช่กราฟแท่งเทียนย้อนหลัง</p>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button type="button" class="btn py-1 text-[10px]" :aria-pressed="showOriginal" @click="showOriginal = !showOriginal">
          {{ showOriginal ? '✓' : '○' }} แผนเดิม
        </button>
        <button type="button" class="btn py-1 text-[10px]" :aria-pressed="showExecuted" @click="showExecuted = !showExecuted">
          {{ showExecuted ? '✓' : '○' }} ราคาจริง
        </button>
        <button type="button" class="btn py-1 text-[10px]" :disabled="!analysis" :aria-pressed="showZones" @click="showZones = !showZones">
          {{ showZones ? '✓' : '○' }} โซน S/R
        </button>
        <button type="button" class="btn py-1 text-[10px]" :disabled="!analysis" :aria-pressed="showFlip" @click="showFlip = !showFlip">
          {{ showFlip ? '✓' : '○' }} SR Flip
        </button>
        <button type="button" class="btn py-1 text-[10px]" :disabled="!analysis" :aria-pressed="showFib" @click="showFib = !showFib">
          {{ showFib ? '✓' : '○' }} Fibonacci
        </button>
        <button type="button" class="btn py-1 text-[10px]" :disabled="!analysis" :aria-pressed="showStructure" @click="showStructure = !showStructure">
          {{ showStructure ? '✓' : '○' }} BOS/CHoCH
        </button>
      </div>
    </div>
    <p v-if="!snapshot?.plan" class="mt-2 text-[10px] text-amber-300">
      ไม่พบบันทึกแผนตอนเข้าไม้ จึงไม่สร้างเส้น SL/TP ย้อนหลังจากราคาปัจจุบัน
    </p>
    <p v-if="!analysis" class="mt-2 text-[10px] text-amber-300">
      ไม่มีหลักฐานโซนในจังหวะตัดสินใจ จึงไม่แสดงแนวรับ–ต้าน / Flip / Fib จากข้อมูลปัจจุบันแทน
    </p>
    <div v-if="levels.length" class="mt-3">
      <svg class="h-[260px] w-full" viewBox="0 0 760 260" preserveAspectRatio="none" role="img"
           aria-label="แผนผังระดับราคาเดิมและราคาซื้อขายจริง">
        <g v-for="item in levels" :key="item.id">
          <line x1="14" x2="746" :y1="levelY(item.price)" :y2="levelY(item.price)"
                :stroke="item.color" :stroke-dasharray="item.executed ? '0' : '7 5'" stroke-width="1.5" />
          <rect x="17" :y="levelY(item.price) - 12" width="156" height="16" rx="3" fill="#111b28" fill-opacity="0.87" />
          <text x="23" :y="levelY(item.price)" :fill="item.color" font-size="11">{{ item.label }} · {{ formatPrice(item.price) }}</text>
        </g>
      </svg>
      <div class="mt-2 flex flex-wrap gap-2 text-[10px] text-muted">
        <span v-for="item in levels" :key="item.id" :style="{ color: item.color }">
          {{ item.label }} {{ formatPrice(item.price) }}
        </span>
      </div>
    </div>
    <p v-else class="mt-2 text-[11px] text-muted">เลือกเปิดการแสดงเส้นด้านบนได้ทุกเมื่อ</p>
    <p class="mt-2 text-[10px] text-muted">ปุ่มเหล่านี้มีผลกับหน้าจอนี้เท่านั้น ไม่เปลี่ยนประวัติ แผน หรือการทำงานของระบบเทรด</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  trade: { type: Object, required: true },
  snapshot: { type: Object, default: null },
  analysis: { type: Object, default: null },
})
const showOriginal = ref(true)
const showExecuted = ref(true)
const showZones = ref(true)
const showFlip = ref(true)
const showFib = ref(true)
const showStructure = ref(false)

function numeric(value) {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
    ? Number(value) : null
}

const levels = computed(() => {
  const result = []
  const add = (id, label, value, color, executed = false) => {
    const price = numeric(value)
    if (price !== null) result.push({ id, label, price, color, executed })
  }
  if (showOriginal.value && props.snapshot?.plan) {
    const plan = props.snapshot.plan
    add('entry', 'Plan entry', plan.entry, '#f5b541')
    add('sl', 'Plan SL', plan.sl, '#f87171')
    add('tp1', 'Plan TP1', plan.tp1, '#34d399')
    add('tp2', 'Plan TP2', plan.tp2, '#34d399')
    add('tp3', 'Plan TP3', plan.tp3, '#34d399')
  }
  if (showExecuted.value) {
    add('actual-entry', 'Fill entry', props.trade.entry, '#60a5fa', true)
    add('actual-exit', 'Closed exit', props.trade.exit, '#a78bfa', true)
  }
  if (props.analysis && showZones.value) {
    const zones = props.analysis.zones || []
    const used = new Set(props.snapshot?.zones_used || [])
    const prioritized = [...zones].sort((a, b) => Number(used.has(b.id)) - Number(used.has(a.id)))
    prioritized.slice(0, 4).forEach((zone) => {
      const color = zone.kind === 'support' ? '#34d399' : '#f87171'
      add(`zone-${zone.id}-low`, `${zone.kind} low`, zone.low, color)
      add(`zone-${zone.id}-high`, `${zone.kind} high`, zone.high, color)
    })
  }
  if (props.analysis && showFlip.value) {
    ;(props.analysis.sr_flips || []).slice(0, 4).forEach((event, index) =>
      add(`flip-${index}`, event.direction === 'resistance_to_support' ? 'Flip R→S' : 'Flip S→R',
        event.level, '#22d3ee'))
  }
  if (props.analysis && showFib.value && props.analysis.fibonacci_band) {
    add('fib-50', 'Fib 50%', props.analysis.fibonacci_band.level_50, '#fbbf24')
    add('fib-618', 'Fib 61.8%', props.analysis.fibonacci_band.level_618, '#f59e0b')
  }
  if (props.analysis && showStructure.value) {
    ;(props.analysis.structure || []).filter((event) => event.confirmed && event.kind !== 'NONE')
      .slice(-3).forEach((event, index) =>
        add(`structure-${index}`, event.kind, event.level, '#c4b5fd'))
  }
  return result
})

const bounds = computed(() => {
  const values = levels.value.map((item) => item.price)
  if (!values.length) return { min: 0, max: 1 }
  const low = Math.min(...values)
  const high = Math.max(...values)
  const padding = Math.max((high - low) * 0.12, Math.abs(high) * 0.00001, 0.00001)
  return { min: low - padding, max: high + padding }
})

function levelY(price) {
  const { min, max } = bounds.value
  return 238 - (price - min) / (max - min) * 216
}

function formatPrice(price) {
  return price.toLocaleString(undefined, { maximumFractionDigits: 6 })
}
</script>
