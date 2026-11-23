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
    <div class="flex gap-1 border-b border-ink-700 px-4 pt-3" role="tablist" aria-label="Calculator tools">
      <button type="button" role="tab" :aria-selected="tool === 'points'" class="btn py-1.5"
        :class="tool === 'points' ? 'border-gold-400/50 text-gold-300' : 'text-muted'" @click="tool = 'points'">
        Points → P&amp;L
      </button>
      <button type="button" role="tab" :aria-selected="tool === 'size'" class="btn py-1.5"
        :class="tool === 'size' ? 'border-gold-400/50 text-gold-300' : 'text-muted'" @click="tool = 'size'">
        Position size
      </button>
    </div>
    <div v-if="tool === 'points'" class="grid gap-3 px-4 py-3 sm:grid-cols-2">
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
    <div v-else class="space-y-3 px-4 py-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="chip chip-gold">MANUAL · SANDBOX</span>
        <span class="text-[10px] text-muted">ไม่มีการอ่านหรือบันทึกยอดเงินในบัญชี</span>
      </div>
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label class="block">
          <span class="label">ทุนจำลอง ({{ spec?.account_currency || 'สกุลบัญชี' }})</span>
          <input v-model.number="equity" type="number" min="0.01" step="100" class="input mt-1 num" placeholder="กรอกทุนจำลอง" />
        </label>
        <label class="block">
          <span class="label">เสี่ยงต่อไม้ (%)</span>
          <input v-model.number="riskPct" type="number" min="0.01" max="100" step="0.05" class="input mt-1 num" />
        </label>
        <label class="block">
          <span class="label">ระยะ Stop Loss (points)</span>
          <input v-model.number="slPoints" type="number" min="0.01" step="10" class="input mt-1 num" />
        </label>
        <div class="kv"><dt>สเปก / point size</dt><dd>{{ spec?.source || '—' }} · {{ spec?.point ?? '—' }}</dd></div>
      </div>
      <div v-if="positionSize?.status === 'ready'" class="grid gap-2 rounded-lg border border-ink-700 bg-ink-900/60 p-3 sm:grid-cols-3">
        <div class="kv"><dt>งบเสี่ยง</dt><dd>{{ accountMoney(positionSize.risk_budget) }}</dd></div>
        <div class="kv"><dt>Lot ที่ไม่เกินงบ</dt><dd class="text-gold-300">{{ fmt(positionSize.lot, lotPrecision(positionSize.lot_step)) }}</dd></div>
        <div class="kv"><dt>ขาดทุนประเมินที่ SL*</dt><dd class="text-down">{{ accountMoney(positionSize.estimated_stop_cost) }}</dd></div>
      </div>
      <p v-else-if="positionSize" class="rounded-lg border border-amber-400/30 bg-amber-400/5 px-3 py-2 text-[10.5px] leading-relaxed text-amber-200">
        {{ positionSize.status === 'no_legal_lot' ? 'ไม่มีขนาด Lot ขั้นต่ำที่อยู่ในงบเสี่ยงนี้' : positionSize.reason }}
        <span v-if="positionSize.estimated_stop_cost != null"> · ขั้นต่ำประเมิน {{ accountMoney(positionSize.estimated_stop_cost) }}</span>
      </p>
      <p class="text-[10px] leading-relaxed text-muted">
        *คำนวณจากสเปก {{ spec?.source || 'ที่ยังไม่ทราบ' }} พร้อม spread ทั่วไปและ commission; ไม่รวม slippage/swap และไม่ใช่คำสั่งซื้อขาย
      </p>
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
import { lotPrecision } from '../lib/lotPrecision'
import { state } from '../lib/store'

const points = ref(750)
const lot = ref(0.01)
const tool = ref('points')
const equity = ref(null)
const riskPct = ref(0.5)
const slPoints = ref(400)
const spec = ref(null)
const result = ref(null)
const positionSize = ref(null)
const provenance = ref(null)
const error = ref('')
let requestId = 0

const symbol = computed(() => state.symbol)
const sourceLabel = computed(() => spec.value?.source === 'broker' ? 'Broker symbol spec' : 'Declared symbol spec')

function accountMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const amount = Number(value)
  const currency = spec.value?.account_currency || 'USD'
  return `${amount < 0 ? '-' : ''}${fmt(Math.abs(amount), 2)} ${currency}`
}

async function load() {
  const activeRequest = ++requestId
  error.value = ''
  positionSize.value = null
  try {
    const query = new URLSearchParams({
      symbol: symbol.value,
      points: String(tool.value === 'size' ? slPoints.value : points.value),
      lot: String(lot.value),
    })
    let endpoint = '/api/market/calculator'
    if (tool.value === 'size') {
      endpoint = '/api/risk/calculator'
      if (equity.value !== null && equity.value !== '' && Number.isFinite(Number(equity.value))) {
        query.set('balance', String(equity.value))
        query.set('risk_pct', String(riskPct.value))
        query.set('sl_points', String(slPoints.value))
      }
    }
    const data = await api.get(`${endpoint}?${query.toString()}`)
    if (activeRequest !== requestId) return
    result.value = data.result || data.points
    spec.value = data.spec
    provenance.value = data.provenance || null
    positionSize.value = data.position_size || null
  } catch (err) {
    if (activeRequest !== requestId) return
    error.value = err.message
  }
}

watch([symbol, points, lot, tool, equity, riskPct, slPoints], load, { immediate: true })
</script>
