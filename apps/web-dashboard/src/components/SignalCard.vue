<template>
  <section class="panel flex h-full flex-col">
    <div class="panel-head">
      <div>
        <div class="panel-title">AI Trading Decision</div>
        <div class="panel-sub">{{ signal ? `${signal.strategy.replace('_', ' ')} · ${signal.regime.replace('_', ' ')}` : 'waiting for the first cycle' }}</div>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="chip" :class="statusChip">{{ signal?.status || 'idle' }}</span>
        <span class="chip chip-gold">{{ modeLabel }}</span>
      </div>
    </div>

    <div class="flex items-start gap-3 px-4 pt-3">
      <ScoreGauge :score="signal?.score || 0" :size="86" label="signal" />
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="rounded-md px-2 py-0.5 text-[15px] font-bold tracking-wide" :class="actionBadge">
            {{ signal?.action?.replace('_', ' ') || 'NO TRADE' }}
          </span>
          <span class="num text-[10.5px] text-muted" v-if="signal">{{ signal.symbol }} · {{ signal.timeframe }}</span>
        </div>
        <p class="mt-1.5 line-clamp-2 text-[11.5px] leading-relaxed text-slate-300">
          {{ headline }}
        </p>
        <div class="mt-2 flex flex-wrap gap-1.5">
          <span v-for="b in (signal?.blockers || []).slice(0, 2)" :key="b" class="chip chip-warn" :title="b">
            {{ truncate(b, 42) }}
          </span>
          <span v-if="signal?.explanation?.calibrated" class="chip chip-up">calibrated model</span>
          <span v-else class="chip">baseline forecast</span>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-2 px-4 pt-3 sm:grid-cols-3">
      <button class="btn btn-buy py-2" :disabled="busy || !perms.canTrade" :title="perms.reason" @click="manual('up')">Buy <span class="text-[10px] opacity-70">manual</span></button>
      <button class="btn btn-sell py-2" :disabled="busy || !perms.canTrade" :title="perms.reason" @click="manual('down')">Sell <span class="text-[10px] opacity-70">manual</span></button>
      <button
        class="btn btn-gold py-2"
        :disabled="busy || !canApprove"
        :title="canApprove ? 'อนุมัติสัญญาณนี้' : 'ไม่มีสัญญาณที่อนุมัติได้ในขณะนี้'"
        @click="approve"
      >
        อนุมัติ ({{ modeLabel }})
      </button>
    </div>

    <div v-if="plan" class="mt-3 border-t border-ink-700/60 px-4 py-3">
      <div class="mb-2 flex items-center justify-between">
        <span class="label">Trade plan · {{ plan.target_mode }} target</span>
        <span class="chip" :class="plan.reward_risk_net >= 1.8 ? 'chip-up' : 'chip-gold'">
          net R:R {{ fmt(plan.reward_risk_net, 2) }}
        </span>
      </div>
      <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-[11.5px] sm:grid-cols-3">
        <div class="kv"><dt>Entry</dt><dd>{{ fmt(plan.entry, digits) }}</dd></div>
        <div class="kv"><dt>Stop</dt><dd class="text-down">{{ fmt(plan.sl, digits) }}</dd></div>
        <div class="kv"><dt>SL distance</dt><dd>{{ fmt(plan.sl_points, 0) }} pts</dd></div>
        <div class="kv"><dt>TP1</dt><dd class="text-up">{{ fmt(plan.tp1, digits) }}</dd></div>
        <div class="kv"><dt>TP2</dt><dd class="text-up">{{ fmt(plan.tp2, digits) }}</dd></div>
        <div class="kv"><dt>TP3</dt><dd class="text-up">{{ fmt(plan.tp3, digits) }}</dd></div>
        <div class="kv"><dt>Lot</dt><dd>{{ fmt(plan.lot, 2) }}</dd></div>
        <div class="kv"><dt>Risk</dt><dd>{{ money(plan.risk_amount) }} ({{ fmt(plan.risk_pct, 2) }}%)</dd></div>
        <div class="kv"><dt>P(TP→SL)</dt><dd>{{ pct(plan.p_tp_before_sl, 0) }}</dd></div>
      </div>
      <div class="mt-2 flex flex-wrap gap-1.5">
        <span v-for="p in plan.partials" :key="p.level" class="chip" :class="p.feasible ? '' : 'chip-warn'">
          TP{{ p.level }} · {{ fmt(p.points, 0) }} pts · {{ fmt(p.close_pct, 0) }}% · {{ fmt(p.volume, 2) }} lot
        </span>
        <span class="chip">costs {{ fmt(plan.estimated_cost, 0) }} pts</span>
        <span class="chip">EV {{ money(plan.expected_value) }}</span>
      </div>
      <p v-if="plan.notes?.length" class="mt-2 text-[10.5px] leading-relaxed text-amber-200/70">
        {{ plan.notes.slice(0, 2).join(' · ') }}
      </p>
    </div>

    <div class="mt-auto border-t border-ink-700/60 px-4 py-3">
      <div class="mb-2 flex items-center justify-between">
        <span class="label">Score breakdown</span>
        <button class="text-[10.5px] text-gold-400/90 hover:text-gold-400" @click="askAi = true">ถาม AI · ทำไม?</button>
      </div>
      <div v-for="c in signal?.components || []" :key="c.key" class="mb-1.5">
        <div class="flex items-center justify-between text-[10.5px]">
          <span class="text-slate-300" :title="c.detail">{{ c.label }}</span>
          <span class="num text-muted">{{ fmt(c.score, 0) }}/{{ fmt(c.max_score, 0) }}</span>
        </div>
        <div class="mt-0.5 h-1 overflow-hidden rounded-full bg-ink-700">
          <div
            class="h-full rounded-full transition-all"
            :class="c.score / c.max_score > 0.66 ? 'bg-up' : c.score / c.max_score > 0.33 ? 'bg-gold-400' : 'bg-ink-600'"
            :style="{ width: `${Math.min(100, (c.score / c.max_score) * 100)}%` }"
          />
        </div>
      </div>
      <div v-if="reasons.length" class="mt-2 space-y-0.5">
        <p v-for="r in reasons.slice(0, 3)" :key="r" class="truncate text-[10.5px] text-muted" :title="r">· {{ r }}</p>
      </div>
    </div>

    <ExplainPanel v-if="askAi" :symbol="state.symbol" @close="askAi = false" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import ExplainPanel from './ExplainPanel.vue'
import ScoreGauge from './ScoreGauge.vue'
import { api } from '../lib/api'
import { fmt, money, pct } from '../lib/format'
import { mode, permissions, signal as liveSignal, state, toast } from '../lib/store'

// Read-only accounts see the buttons disabled — the server refuses them anyway.
const perms = computed(() => permissions.value)

const props = defineProps({ gate: { type: Object, default: null } })
const busy = ref(false)
const askAi = ref(false)
const signal = computed(() => liveSignal.value)
const plan = computed(() => signal.value?.plan || null)
const digits = computed(() => state.live?.analysis?.spec?.digits ?? 2)
const modeLabel = computed(() => ({ manual: 'Manual', semi_auto: 'Semi-Auto', full_auto: 'Full Auto' }[mode.value] || mode.value))
const canApprove = computed(() => ['BUY', 'SELL'].includes(signal.value?.action) && (signal.value?.score || 0) >= 50 && !signal.value?.executed_order_id)
const reasons = computed(() => signal.value?.reasons || [])
const headline = computed(() => {
  if (!signal.value) return 'รอรอบวิเคราะห์ถัดไป…'
  if (signal.value.action === 'BUY' || signal.value.action === 'SELL') {
    return `${signal.value.action} signal ที่คะแนน ${fmt(signal.value.score, 0)}/100 — ผ่านเงื่อนไขครบและ Risk Gate เปิดให้เข้าไม้`
  }
  if (signal.value.blockers?.length) return `ยังไม่เข้าเทรด: ${signal.value.blockers[0]}`
  return 'สภาพตลาดยังไม่ให้น้ำหนักเพียงพอ — ระบบเลือกไม่เทรด'
})
const statusChip = computed(() => {
  const s = signal.value?.status
  return s === 'strong' ? 'chip-up' : s === 'valid' ? 'chip-gold' : s === 'weak' ? 'chip-warn' : 'chip'
})
const actionBadge = computed(() => {
  const a = signal.value?.action
  if (a === 'BUY') return 'bg-up/15 text-up ring-1 ring-up/30'
  if (a === 'SELL') return 'bg-down/15 text-down ring-1 ring-down/30'
  if (a === 'WAIT') return 'bg-amber-400/10 text-amber-300 ring-1 ring-amber-400/25'
  return 'bg-ink-700/60 text-muted ring-1 ring-ink-600'
})

const truncate = (s, n) => (s && s.length > n ? `${s.slice(0, n)}…` : s)

async function manual(direction) {
  busy.value = true
  try {
    const res = await api.post('/api/trading/order', { symbol: state.symbol, direction })
    toast(`เปิดไม้ ${direction === 'up' ? 'BUY' : 'SELL'} สำเร็จ · ticket ${res.order?.ticket}`, 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}

async function approve() {
  if (!signal.value) return
  busy.value = true
  try {
    await api.post(`/api/signals/${signal.value.id}/approve`)
    toast('อนุมัติสัญญาณและส่งคำสั่งแล้ว', 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}
</script>
