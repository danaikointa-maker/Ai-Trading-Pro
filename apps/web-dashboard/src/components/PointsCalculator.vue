<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Points → Profit Calculator</div>
        <div class="panel-sub">ใช้ spec จริงของสัญลักษณ์ (point / tick size / contract)</div>
      </div>
      <span class="chip chip-gold">{{ spec?.symbol || state.symbol }}</span>
    </div>
    <div class="grid gap-3 px-4 py-3 sm:grid-cols-2">
      <label class="block">
        <span class="label">Target per trade (points)</span>
        <div class="mt-1 flex items-center gap-2">
          <input v-model.number="points" type="range" min="500" max="1000" step="50" class="w-full accent-gold-400" />
          <span class="num w-14 text-right text-[12px] text-gold-400">{{ points }}</span>
        </div>
      </label>
      <label class="block">
        <span class="label">Trade lot</span>
        <input v-model.number="lot" type="number" min="0.01" step="0.01" class="input mt-1 num" />
      </label>
      <div class="kv"><dt>Point size</dt><dd>{{ spec?.point ?? '—' }}</dd></div>
      <div class="kv"><dt>Contract size</dt><dd>{{ fmt(spec?.contract_size, 0) }}</dd></div>
      <div class="kv"><dt>Price movement</dt><dd>{{ fmt(result?.price_move, spec?.digits ?? 2) }}</dd></div>
      <div class="kv"><dt>Gross profit</dt><dd class="text-up">{{ money(result?.gross_profit) }}</dd></div>
      <div class="kv"><dt>Value / point / lot</dt><dd>{{ money(result?.value_per_point_per_lot) }}</dd></div>
      <div class="kv"><dt>Spread cost @ typical</dt><dd class="text-down">{{ money(result?.spread_cost) }}</dd></div>
    </div>
    <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
      ตัวอย่าง: XAUUSD ที่ point = 0.01 → 500 points = $5.00, 750 = $7.50, 1,000 = $10.00 ต่อราคา
      แต่ถ้า point = 0.001 ระยะ 500 points จะเหลือเพียง $0.50 ของการเคลื่อนไหวราคา
      ตัวเลขนี้ยังไม่รวม spread, commission, swap และ slippage
    </p>
    <p v-if="error" class="px-4 pb-3 text-[10.5px] text-down">{{ error }}</p>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fmt, money } from '../lib/format'
import { state } from '../lib/store'

const points = ref(750)
const lot = ref(0.01)
const spec = ref(null)
const result = ref(null)
const error = ref('')

const symbol = computed(() => state.symbol)

async function load() {
  error.value = ''
  try {
    const data = await api.get(`/api/market/calculator?symbol=${symbol.value}&points=${points.value}&lot=${lot.value}`)
    result.value = data.result
    spec.value = data.spec
  } catch (err) {
    error.value = err.message
  }
}

watch([symbol, points, lot], load, { immediate: true })
</script>
