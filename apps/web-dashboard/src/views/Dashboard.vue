<template>
  <div class="space-y-3">
    <div class="flex flex-wrap items-center gap-2 rounded-xl border border-ink-700/70 bg-ink-850/70 px-3 py-2">
      <span class="chip chip-gold">AI Trading Terminal</span>
      <span class="chip">{{ analysis?.regime?.regime?.replace('_', ' ') || '—' }}</span>
      <span class="chip">ADX {{ fmt(analysis?.indicators?.adx14, 1) }}</span>
      <span class="chip">ATR {{ fmt(analysis?.indicators?.atr_points, 0) }} pts ({{ fmt(atrPct, 2) }}%)</span>
      <span class="chip">VWAP {{ fmt(analysis?.indicators?.vwap, digits) }}</span>
      <span class="chip">EQ {{ money(account?.equity) }}</span>
      <ModelBadge class="ml-auto" />
    </div>

    <div v-if="news?.active" class="rounded-xl border border-amber-400/30 bg-amber-400/10 px-4 py-2.5 text-[11.5px] text-amber-200">
      <span v-if="news.provisional" class="mr-1 rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide">
        ปฏิทินตัวอย่าง
      </span>
      <strong>News lockout:</strong> {{ news.reason }} — ระบบจะไม่เปิดไม้ใหม่จนกว่าจะพ้นช่วงข่าว
    </div>
    <div v-if="!analysis?.data_quality?.ok" class="rounded-xl border border-down/30 bg-down/10 px-4 py-2.5 text-[11.5px] text-down">
      <strong>Data quality:</strong> {{ analysis?.data_quality?.reason }} — ห้ามเปิดออร์เดอร์เมื่อข้อมูลไม่สด
    </div>

    <div class="grid grid-cols-2 gap-2 lg:grid-cols-4">
      <Stat label="Equity" :value="money(account?.equity)" :hint="`Balance ${money(account?.balance)}`" />
      <Stat label="Today P&L" :value="money(risk?.daily_pnl)" :tone="(risk?.daily_pnl||0) >= 0 ? 'text-up' : 'text-down'"
            :hint="`${fmt(risk?.daily_pnl_pct,2)}% · limit ${fmt(limits?.max_daily_loss_pct,1)}%`" />
      <Stat label="Trade mode" :value="modeLabel" :hint="modeHint" tone="text-gold-400" />
      <Stat label="Decisions today" :value="risk?.trades_today ?? 0" :hint="`max open ${limits?.max_open_trades ?? 1}`" />
    </div>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-3">
        <section class="panel overflow-hidden">
          <div class="flex flex-wrap items-center justify-between gap-2 px-3 pt-2.5">
            <div class="flex items-center gap-2">
              <span class="panel-title">Price structure</span>
              <span class="chip">EMA20/50/200</span>
              <span class="chip">zones</span>
              <span class="chip">plan levels</span>
            </div>
            <div class="flex items-center gap-1.5">
              <select v-model.number="state.range" class="input w-[92px] py-1 text-[11px]">
                <option :value="120">120 bars</option>
                <option :value="240">240 bars</option>
                <option :value="480">480 bars</option>
                <option :value="800">800 bars</option>
              </select>
              <span class="chip">session H {{ fmt(analysis?.session_high, digits) }} / L {{ fmt(analysis?.session_low, digits) }}</span>
            </div>
          </div>
          <PriceChart />
        </section>

        <div class="grid gap-3 md:grid-cols-2">
          <section class="panel px-3 py-3">
            <div class="mb-2 flex items-center justify-between">
              <span class="panel-title">Multi-timeframe trend</span>
              <span class="chip">alignment {{ pct(live?.signal?.explanation?.alignment ?? 0, 0) }}</span>
            </div>
            <TrendStrip />
            <div class="mt-2.5 space-y-1">
              <div v-for="e in (analysis?.structure || []).slice(-3).reverse()" :key="e.t + e.kind" class="flex items-center justify-between text-[10.5px]">
                <span class="flex items-center gap-1.5">
                  <span class="chip" :class="e.direction === 'up' ? 'chip-up' : 'chip-down'">{{ e.kind }}</span>
                  <span class="text-muted">{{ e.direction }} @ {{ fmt(e.level, digits) }}</span>
                </span>
                <span class="num text-muted">{{ e.bars_ago }} bars ago</span>
              </div>
            </div>
          </section>

          <section class="panel px-3 py-3">
            <div class="mb-2 flex items-center justify-between">
              <span class="panel-title">Forecast · 3 scenarios</span>
              <RouterLink to="/forecast" class="chip hover:text-slate-200">details →</RouterLink>
            </div>
            <div v-if="primary" class="space-y-2">
              <div class="flex items-end justify-between">
                <div>
                  <div class="label">Primary horizon</div>
                  <div class="num text-[15px] font-semibold text-slate-100">{{ primary.horizon_minutes }} min</div>
                </div>
                <div class="text-right">
                  <div class="label">P(TP before SL)</div>
                  <div class="num text-[15px] font-semibold" :class="primary.p_tp_before_sl > 0.45 ? 'text-up' : 'text-amber-300'">
                    {{ pct(primary.p_tp_before_sl, 0) }}
                  </div>
                </div>
              </div>
              <ProbBars :p-up="primary.p_up" :p-down="primary.p_down" :p-side="primary.p_sideways" />
              <div class="grid grid-cols-3 gap-1.5 text-center">
                <div v-for="s in forecast?.scenarios || []" :key="s.name" class="rounded-lg border border-ink-700/70 bg-ink-900/60 px-1.5 py-1.5">
                  <div class="text-[9.5px] uppercase tracking-wide text-muted">{{ s.name }}</div>
                  <div class="num text-[11.5px]" :class="s.name === 'bull' ? 'text-up' : s.name === 'bear' ? 'text-down' : 'text-slate-200'">
                    {{ fmt(s.target_price, digits) }}
                  </div>
                  <div class="num text-[9px] text-muted">{{ pct(s.probability, 0) }}</div>
                </div>
              </div>
              <p class="text-[10px] leading-relaxed text-muted">
                {{ forecast?.model_approved ? 'โมเดลผ่านเกณฑ์ OOS บางช่วง' : 'ยังไม่มีโมเดลผ่านเกณฑ์ — ใช้ค่าฐานสถิติ' }}
                · ช่วง P10–P90 {{ fmt(primary.p10_price, digits) }}–{{ fmt(primary.p90_price, digits) }}
              </p>
            </div>
            <p v-else class="py-6 text-center text-[11px] text-muted">กำลังคำนวณ forecast…</p>
          </section>
        </div>

        <PositionsTable />
      </div>

      <div class="space-y-3">
        <SignalCard :gate="live?.gate" />
        <RiskPanel />
        <AlertFeed />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AlertFeed from '../components/AlertFeed.vue'
import ModelBadge from '../components/ModelBadge.vue'
import PositionsTable from '../components/PositionsTable.vue'
import PriceChart from '../components/PriceChart.vue'
import ProbBars from '../components/ProbBars.vue'
import RiskPanel from '../components/RiskPanel.vue'
import SignalCard from '../components/SignalCard.vue'
import Stat from '../components/Stat.vue'
import TrendStrip from '../components/TrendStrip.vue'
import { fmt, money, pct } from '../lib/format'
import { state } from '../lib/store'

const live = computed(() => state.live)
const analysis = computed(() => live.value?.analysis || null)
const forecast = computed(() => live.value?.forecast || null)
const account = computed(() => live.value?.account || null)
const risk = computed(() => live.value?.risk_state || null)
const limits = computed(() => live.value?.limits || null)
const news = computed(() => analysis.value?.news_lockout || null)
const digits = computed(() => analysis.value?.spec?.digits ?? 2)
const atrPct = computed(() => {
  const a = analysis.value
  return a ? (a.indicators.atr14 / a.price) * 100 : 0
})
const primary = computed(() => {
  const hs = forecast.value?.horizons || []
  if (!hs.length) return null
  return hs.find((h) => h.horizon_minutes === 60) || hs[Math.floor(hs.length / 2)]
})
const modeLabel = computed(() => ({ manual: 'Manual + AI', semi_auto: 'Semi-Auto', full_auto: 'Full Auto' }[live.value?.mode] || '—'))
const modeHint = computed(() => ({
  manual: 'ผู้ใช้กด Buy/Sell เอง',
  semi_auto: 'ผู้อนุมัติสัญญาณ ระบบจัดการ SL/TP',
  full_auto: 'EA เปิดไม้ตามกฎ + Risk Engine',
}[live.value?.mode] || ''))
</script>
