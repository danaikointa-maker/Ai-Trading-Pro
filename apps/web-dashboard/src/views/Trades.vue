<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Trades & Performance</h1>
        <p class="text-[11px] text-muted">วัดผลจากไม้ที่ปิดแล้วจริง — ไม่มีการปรับตัวเลขย้อนหลัง</p>
      </div>
      <div class="ml-auto flex gap-1.5">
        <button class="btn py-1.5" @click="load">Refresh</button>
        <button class="btn btn-danger py-1.5" @click="closeAll">Close all</button>
      </div>
    </header>

    <div class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
      <Stat label="Net P&L" :value="money(m?.net_profit)" :tone="(m?.net_profit || 0) >= 0 ? 'text-up' : 'text-down'" />
      <Stat label="Profit factor" :value="fmt(m?.profit_factor, 2)" :hint="'target > 1.30'" />
      <Stat label="Expectancy" :value="money(m?.expectancy)" :hint="`${fmt(m?.expectancy_r, 2)}R avg`" />
      <Stat label="Win rate" :value="pct((m?.win_rate || 0) / 100, 1)" :hint="`${m?.wins || 0}W / ${m?.losses || 0}L`" />
      <Stat label="Max drawdown" :value="`${fmt(m?.max_drawdown_pct, 2)}%`" tone="text-down" />
      <Stat label="Sharpe" :value="fmt(m?.sharpe, 2)" />
      <Stat label="TP before SL" :value="pct((m?.tp_before_sl_rate || 0) / 100, 0)" />
      <Stat label="Trades" :value="m?.trades ?? 0" :hint="`costs ${money(m?.total_costs)}`" />
    </div>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_330px]">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">Equity curve</div>
          <span class="chip">live account · {{ curve.length }} points</span>
        </div>
        <div class="px-2 py-2">
          <EquityChart :curve="curve" :baseline="startingBalance" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div class="panel-title">Exit distribution</div></div>
        <div class="space-y-1.5 px-4 py-3">
          <div v-for="(v, k) in byExit" :key="k" class="flex items-center justify-between text-[11px]">
            <span class="capitalize text-slate-300">{{ k.replaceAll('_', ' ') }}</span>
            <span class="flex items-center gap-2">
              <span class="chip">{{ v.count }}</span>
              <span class="num" :class="v.pnl >= 0 ? 'text-up' : 'text-down'">{{ money(v.pnl) }}</span>
            </span>
          </div>
          <p v-if="!Object.keys(byExit).length" class="py-4 text-center text-[11px] text-muted">ยังไม่มีข้อมูล</p>
        </div>
        <div class="border-t border-ink-700/60 px-4 py-3 text-[10px] leading-relaxed text-muted">
          {{ payload?.note }}
        </div>
      </section>
    </div>

    <PositionsTable />

    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">Closed trades</div>
        <span class="chip">{{ trades.length }} records</span>
      </div>
      <div class="overflow-x-auto">
        <table class="table-base">
          <thead>
            <tr><th>Closed</th><th>Symbol</th><th>Side</th><th>Lot</th><th>Entry</th><th>Exit</th><th>Points</th>
              <th>P&L</th><th>R</th><th>Exit reason</th><th>Strategy</th><th>Mode</th></tr>
          </thead>
          <tbody>
            <tr v-for="t in trades" :key="t.ticket" class="hover:bg-ink-800/40">
              <td class="num text-[10.5px] text-muted">{{ datetime(t.closed_at) }}</td>
              <td>{{ t.symbol }}</td>
              <td><span class="chip" :class="t.direction === 'up' ? 'chip-up' : 'chip-down'">{{ t.direction === 'up' ? 'BUY' : 'SELL' }}</span></td>
              <td class="num">{{ fmt(t.volume, 2) }}</td>
              <td class="num">{{ fmt(t.entry, 2) }}</td>
              <td class="num">{{ fmt(t.exit, 2) }}</td>
              <td class="num" :class="t.points >= 0 ? 'text-up' : 'text-down'">{{ fmt(t.points, 0) }}</td>
              <td class="num" :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ money(t.pnl) }}</td>
              <td class="num">{{ fmt(t.r_multiple, 2) }}</td>
              <td class="text-[10.5px] capitalize text-muted">{{ (t.exit_reason || '').replaceAll('_', ' ') }}</td>
              <td class="text-[10.5px] text-muted">{{ (t.strategy || '—').replaceAll('_', ' ') }}</td>
              <td class="text-[10.5px] text-muted">{{ t.mode }}</td>
            </tr>
            <tr v-if="!trades.length"><td colspan="12" class="py-6 text-center text-[11px] text-muted">ยังไม่มีไม้ที่ปิดแล้ว</td></tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import EquityChart from '../components/EquityChart.vue'
import PositionsTable from '../components/PositionsTable.vue'
import Stat from '../components/Stat.vue'
import { api } from '../lib/api'
import { datetime, fmt, money, pct } from '../lib/format'
import { state, toast } from '../lib/store'

const payload = ref(null)
const trades = ref([])
const startingBalance = 10000

const m = computed(() => payload.value?.metrics || {})
const curve = computed(() => payload.value?.equity_curve || [])
const byExit = computed(() => payload.value?.by_exit_reason || {})

async function load() {
  try {
    const [perf, hist] = await Promise.all([
      api.get('/api/trading/performance'),
      api.get('/api/trading/trades?limit=100'),
    ])
    payload.value = perf
    trades.value = hist.trades || []
  } catch (err) {
    toast(err.message, 'error')
  }
}
async function closeAll() {
  if (!confirm('ปิดทุกไม้ที่เปิดอยู่?')) return
  try {
    await api.post('/api/trading/close-all')
    toast('ปิดทุกไม้แล้ว', 'success')
    await load()
  } catch (err) {
    toast(err.message, 'error')
  }
}

onMounted(load)
</script>
