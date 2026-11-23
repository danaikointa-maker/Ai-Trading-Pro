<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Points → Profit Calculator</div>
        <div class="panel-sub">{{ sourceLabel }} · {{ spec?.account_currency || '—' }} · FX {{ spec?.rate_source || '—' }}</div>
      </div>
      <span class="chip" :class="spec?.source === 'broker' ? 'chip-up' : 'chip-gold'" :title="`Feed: ${provenance?.market_feed || '—'}`">
        {{ spec?.symbol || state.symbol }} · {{ spec?.source || '—' }}
      </span>
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
      <div class="kv"><dt>Gross profit</dt><dd class="text-up">{{ accountMoney(result?.gross_profit) }}</dd></div>
      <div class="kv"><dt>Commission</dt><dd class="text-down">{{ accountMoney(result?.commission) }}</dd></div>
      <div class="kv"><dt>Net after commission</dt><dd>{{ accountMoney(result?.net_profit) }}</dd></div>
      <div class="kv"><dt>Value / point / lot</dt><dd>{{ accountMoney(result?.value_per_point_per_lot) }}</dd></div>
      <div class="kv"><dt>Spread @ typical</dt><dd class="text-down">{{ accountMoney(result?.spread_cost) }}</dd></div>
      <div class="kv"><dt>Net after known costs</dt><dd class="text-gold-400">{{ accountMoney(result?.net_after_known_costs) }}</dd></div>
    </div>
    <p v-if="result && !result.valuation_valid" class="border-t border-amber-400/30 px-4 py-2 text-[10px] leading-relaxed text-amber-300">
      สเปกหรืออัตราแปลงสกุลเงินยังไม่ครบ จึงไม่แสดงยอดกำไร/ขาดทุนเป็นตัวเลข
    </p>
    <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
      ตัวอย่าง: XAUUSD ที่ point = 0.01 → 500 points = $5.00, 750 = $7.50, 1,000 = $10.00 ต่อราคา
      แต่ถ้า point = 0.001 ระยะ 500 points จะเหลือเพียง $0.50 ของการเคลื่อนไหวราคา
      Net after known costs หัก typical spread และ commission แล้ว; ยังไม่รวม swap และ slippage
    </p>
    <p v-if="error" class="px-4 pb-3 text-[10.5px] text-down">{{ error }}</p>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { state } from '../lib/store'

const points = ref(750)
const lot = ref(0.01)
const spec = ref(null)
const result = ref(null)
const provenance = ref(null)
const error = ref('')

const symbol = computed(() => state.symbol)
const sourceLabel = computed(() => spec.value?.source === 'broker' ? 'Broker symbol spec' : 'Declared symbol spec')

function accountMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const amount = Number(value)
  const currency = spec.value?.account_currency || 'USD'
  return `${amount < 0 ? '-' : ''}${fmt(Math.abs(amount), 2)} ${currency}`
}

async function load() {
  error.value = ''
  try {
    const data = await api.get(`/api/market/calculator?symbol=${symbol.value}&points=${points.value}&lot=${lot.value}`)
    result.value = data.result
    spec.value = data.spec
    provenance.value = data.provenance || null
  } catch (err) {
    error.value = err.message
  }
}

watch([symbol, points, lot], load, { immediate: true })
</script>
