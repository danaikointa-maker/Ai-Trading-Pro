<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Backtest Lab</h1>
        <p class="text-[11px] text-muted">ทดสอบย้อนหลังพร้อม spread, commission, slippage และการจัดการไม้จริง</p>
      </div>
      <span class="ml-auto chip chip-warn">ผลทดสอบย้อนหลังไม่รับประกันอนาคต</span>
    </header>

    <div class="grid gap-3 xl:grid-cols-[330px_minmax(0,1fr)]">
      <section class="panel h-fit">
        <div class="panel-head"><div class="panel-title">Run configuration</div></div>
        <div class="space-y-2.5 px-4 py-3">
          <label class="block"><span class="label">Symbol</span>
            <select v-model="form.symbol" class="input mt-1">
              <option v-for="s in symbols" :key="s" :value="s">{{ s }}</option>
            </select>
          </label>
          <label class="block"><span class="label">Bars (M1)</span>
            <input v-model.number="form.bars" type="number" min="1200" max="20000" step="500" class="input mt-1 num" />
          </label>
          <div class="grid grid-cols-2 gap-2">
            <label class="block"><span class="label">Spread (pts)</span>
              <input v-model.number="form.spread_points" type="number" min="0" step="1" class="input mt-1 num" placeholder="auto" />
            </label>
            <label class="block"><span class="label">Slippage (pts)</span>
              <input v-model.number="form.slippage_points" type="number" min="0" step="0.5" class="input mt-1 num" />
            </label>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <label class="block"><span class="label">Commission / lot</span>
              <input v-model.number="form.commission_per_lot" type="number" min="0" step="0.5" class="input mt-1 num" placeholder="auto" />
            </label>
            <label class="block"><span class="label">Balance</span>
              <input v-model.number="form.starting_balance" type="number" min="100" step="500" class="input mt-1 num" />
            </label>
          </div>
          <label class="flex items-center gap-2 text-[11px] text-slate-300">
            <input v-model="form.validate_walk_forward" type="checkbox" class="accent-gold-400" /> walk-forward fold report
          </label>
          <button class="btn btn-gold w-full py-2" :disabled="running" @click="run">
            {{ running ? `${job?.message || 'running'} ${job?.pct || 0}%` : 'Run backtest' }}
          </button>
          <p class="text-[9.5px] leading-relaxed text-muted">
            ใช้ข้อมูลที่ระบบมี (simulated feed หรือ MT5 history) · แนะนำให้เปลี่ยนเป็น tick data จริงก่อนตัดสินใจ
          </p>
        </div>
      </section>

      <div class="space-y-3">
        <div class="flex flex-wrap gap-1.5">
          <button v-for="r in reports" :key="r.id" class="chip"
                  :class="selected?.id === r.id ? 'chip-gold' : 'hover:text-slate-200'"
                  @click="select(r.id)">
            {{ r.id }} · {{ datetime(r.created_at) }} · {{ r.metrics?.trades || 0 }} trades
          </button>
          <span v-if="!reports.length" class="chip">ยังไม่มีรายงาน — กด Run backtest</span>
        </div>

        <template v-if="report">
          <div class="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
            <Stat label="Net" :value="money(report.metrics.net_profit)" :tone="report.metrics.net_profit >= 0 ? 'text-up' : 'text-down'" />
            <Stat label="Profit factor" :value="fmt(report.metrics.profit_factor, 2)" />
            <Stat label="Expectancy" :value="money(report.metrics.expectancy)" :hint="`${fmt(report.metrics.expectancy_r, 2)}R`" />
            <Stat label="Trades" :value="report.metrics.trades" :hint="`no-trade ${fmt(report.metrics.no_trade_rate, 0)}%`" />
            <Stat label="Win rate" :value="`${fmt(report.metrics.win_rate, 1)}%`" />
            <Stat label="Max DD" :value="`${fmt(report.metrics.max_drawdown_pct, 2)}%`" tone="text-down" />
            <Stat label="Sharpe" :value="fmt(report.metrics.sharpe, 2)" />
            <Stat label="Costs" :value="money(report.metrics.total_costs)" />
          </div>

          <div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
            <section class="panel">
              <div class="panel-head"><div class="panel-title">Equity curve</div>
                <span class="chip">{{ fmt(report.from_t, 0) }} → {{ fmt(report.to_t, 0) }}</span></div>
              <div class="px-2 py-2"><EquityChart :curve="report.equity_curve" :baseline="form.starting_balance" /></div>
            </section>
            <section class="panel">
              <div class="panel-head"><div class="panel-title">Verdict</div>
                <span class="chip" :class="report.verdict?.passed ? 'chip-up' : 'chip-warn'">{{ report.verdict?.passed ? 'PASS' : 'FAIL' }}</span></div>
              <div class="space-y-1.5 px-4 py-3">
                <div v-for="c in report.verdict?.checks || []" :key="c.name" class="flex items-start justify-between gap-2 text-[10.5px]">
                  <span class="text-slate-300">{{ c.name }}</span>
                  <span class="shrink-0 text-right">
                    <span class="num text-muted">{{ typeof c.value === 'number' ? fmt(c.value, 2) : c.value }}</span>
                    <span class="ml-1" :class="c.pass ? 'text-up' : 'text-down'">{{ c.pass ? '✓' : '✗' }}</span>
                  </span>
                </div>
                <p class="mt-2 text-[10px] leading-relaxed text-muted">{{ report.verdict?.summary }}</p>
              </div>
            </section>
          </div>

          <div class="grid gap-3 lg:grid-cols-2">
            <section class="panel">
              <div class="panel-head"><div class="panel-title">Walk-forward folds</div></div>
              <table class="table-base">
                <thead><tr><th>Fold</th><th>Trades</th><th>Net</th><th>PF</th><th>Win%</th><th>Max DD</th></tr></thead>
                <tbody>
                  <tr v-for="f in report.walk_forward || []" :key="f.fold">
                    <td>{{ f.fold }}</td><td class="num">{{ f.trades }}</td>
                    <td class="num" :class="f.net_profit >= 0 ? 'text-up' : 'text-down'">{{ money(f.net_profit) }}</td>
                    <td class="num">{{ fmt(f.profit_factor, 2) }}</td>
                    <td class="num">{{ fmt(f.win_rate, 1) }}</td>
                    <td class="num">{{ fmt(f.max_drawdown_pct, 2) }}</td>
                  </tr>
                </tbody>
              </table>
            </section>
            <section class="panel">
              <div class="panel-head"><div class="panel-title">Assumptions & limitations</div></div>
              <ul class="space-y-1.5 px-4 py-3">
                <li v-for="a in report.assumptions || []" :key="a" class="flex gap-2 text-[10px] leading-relaxed text-muted">
                  <span class="mt-1 h-1 w-1 shrink-0 rounded-full bg-amber-400"></span>{{ a }}
                </li>
              </ul>
            </section>
          </div>

          <section class="panel">
            <div class="panel-head"><div class="panel-title">Trades</div><span class="chip">{{ report.trades?.length || 0 }} shown</span></div>
            <div class="max-h-[320px] overflow-auto">
              <table class="table-base">
                <thead><tr><th>#</th><th>Side</th><th>Entry</th><th>Exit</th><th>Points</th><th>P&L</th><th>R</th><th>Exit</th><th>Strategy</th></tr></thead>
                <tbody>
                  <tr v-for="(t, i) in report.trades || []" :key="t.ticket">
                    <td class="num text-muted">{{ i + 1 }}</td>
                    <td><span class="chip" :class="t.direction === 'up' ? 'chip-up' : 'chip-down'">{{ t.direction === 'up' ? 'BUY' : 'SELL' }}</span></td>
                    <td class="num">{{ fmt(t.entry, 2) }}</td>
                    <td class="num">{{ fmt(t.exit, 2) }}</td>
                    <td class="num" :class="t.points >= 0 ? 'text-up' : 'text-down'">{{ fmt(t.points, 0) }}</td>
                    <td class="num" :class="t.pnl >= 0 ? 'text-up' : 'text-down'">{{ money(t.pnl) }}</td>
                    <td class="num">{{ fmt(t.r_multiple, 2) }}</td>
                    <td class="text-[10.5px] capitalize text-muted">{{ (t.exit_reason || '').replaceAll('_', ' ') }}</td>
                    <td class="text-[10.5px] text-muted">{{ (t.strategy || '—').replaceAll('_', ' ') }}</td>
                  </tr>
                  <tr v-if="!report.trades?.length"><td colspan="9" class="py-5 text-center text-[11px] text-muted">ไม่มีไม้ในรอบนี้</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </template>
        <div v-else class="panel px-4 py-10 text-center text-[11.5px] text-muted">
          เลือกหรือสร้างรายงานเพื่อดูผลลัพธ์ · ระบบจะแสดงผลแม้ไม่มีไม้ (no-trade rate) เพื่อไม่ให้เข้าใจผิดว่ากลยุทธ์ได้ผล
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import EquityChart from '../components/EquityChart.vue'
import Stat from '../components/Stat.vue'
import { api } from '../lib/api'
import { datetime, fmt, money } from '../lib/format'
import { state, toast } from '../lib/store'

const form = reactive({
  symbol: state.symbol || 'XAUUSD', bars: 6000, spread_points: null, commission_per_lot: null,
  slippage_points: 2, starting_balance: 10000, validate_walk_forward: true, strategy: 'all',
})
const symbols = computed(() => state.config?.symbols || ['XAUUSD'])
const reports = ref([])
const selectedId = ref(null)
const report = ref(null)
const job = ref(null)
const running = ref(false)
let timer = null

function select(id) {
  selectedId.value = id
  api.get(`/api/backtests/${id}`).then((data) => (report.value = data)).catch((err) => toast(err.message, 'error'))
}

async function loadReports() {
  try {
    const data = await api.get('/api/backtests')
    reports.value = data.reports || []
    if (!selectedId.value && reports.value.length) select(reports.value[0].id)
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function run() {
  running.value = true
  try {
    const payload = { ...form }
    if (!payload.spread_points) delete payload.spread_points
    if (!payload.commission_per_lot) delete payload.commission_per_lot
    const started = await api.post('/api/backtests', payload)
    toast('เริ่มทดสอบย้อนหลัง…', 'info')
    timer = setInterval(async () => {
      const j = await api.get(`/api/backtests/jobs/${started.job_id}`).catch(() => null)
      job.value = j
      if (j && (j.state === 'done' || j.state === 'error')) {
        clearInterval(timer)
        running.value = false
        if (j.state === 'done') {
          toast('ทดสอบเสร็จแล้ว', 'success')
          await loadReports()
          select(j.report_id)
        } else {
          toast(j.message, 'error')
        }
      }
    }, 1500)
  } catch (err) {
    running.value = false
    toast(err.message, 'error')
  }
}

onMounted(loadReports)
onUnmounted(() => timer && clearInterval(timer))
</script>
