<template>
  <header class="sticky top-0 z-30 border-b border-ink-700/70 bg-ink-950/85 backdrop-blur">
    <div class="mx-auto flex max-w-[1700px] flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5 sm:px-4">
      <div class="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 p-0.5">
        <button
          v-for="s in symbols"
          :key="s"
          class="rounded-md px-2.5 py-1 text-[11.5px] font-semibold transition"
          :class="state.symbol === s ? 'bg-gold-500/15 text-gold-400 ring-1 ring-gold-500/30' : 'text-muted hover:text-slate-200'"
          @click="switchSymbol(s)"
        >
          {{ s }}
        </button>
      </div>

      <div v-if="ticker" class="flex items-baseline gap-2">
        <span class="num text-[17px] font-semibold text-slate-100">{{ fmt(ticker.last, digits) }}</span>
        <span class="num text-[11px]" :class="change >= 0 ? 'text-up' : 'text-down'">
          {{ signed(change, digits) }} ({{ signed(changePct, 2) }}%)
        </span>
        <span class="chip num">spread {{ fmt(ticker.spread_points, 0) }} pts</span>
      </div>

      <div class="ml-auto flex flex-wrap items-center gap-2">
        <div class="hidden items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 p-0.5 md:flex">
          <button
            v-for="tf in timeframes"
            :key="tf"
            class="rounded-md px-2 py-1 text-[10.5px] font-medium transition"
            :class="state.timeframe === tf ? 'bg-ink-700 text-slate-100' : 'text-muted hover:text-slate-200'"
            @click="setTimeframe(tf)"
          >
            {{ tf }}
          </button>
        </div>

        <div class="hidden text-right sm:block">
          <div class="label">Equity</div>
          <div class="num text-[13px] font-semibold text-slate-100">{{ money(account?.equity) }}</div>
        </div>
        <div class="hidden text-right sm:block">
          <div class="label">Today</div>
          <div class="num text-[13px] font-semibold" :class="(risk?.daily_pnl || 0) >= 0 ? 'text-up' : 'text-down'">
            {{ money(risk?.daily_pnl) }}
            <span class="text-[10px] text-muted">({{ fmt(risk?.daily_pnl_pct, 2) }}%)</span>
          </div>
        </div>

        <div class="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 p-0.5">
          <button
            v-for="m in modes"
            :key="m.id"
            class="rounded-md px-2.5 py-1 text-[10.5px] font-semibold transition"
            :class="mode === m.id ? 'bg-gold-500/15 text-gold-400 ring-1 ring-gold-500/30' : 'text-muted hover:text-slate-200'"
            :title="m.hint"
            @click="changeMode(m.id)"
          >
            {{ m.label }}<span v-if="m.id === 'full_auto' && !fullAutoAllowed" class="ml-1 opacity-60">🔒</span>
          </button>
        </div>

        <div class="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900 px-2 py-1.5">
          <span class="h-1.5 w-1.5 rounded-full" :class="healthTone" />
          <span class="text-[10.5px] capitalize text-slate-300">{{ health }}</span>
        </div>

        <div class="hidden text-right lg:block">
          <div class="label">Market clock</div>
          <div class="num text-[12px] text-slate-300">{{ clock(state.live?.virtual_time) }}</div>
        </div>

        <span v-if="role" class="chip" :class="roleTone" :title="roleHint">{{ role }}</span>

        <button class="btn px-2" title="Sign out" @click="signOut">
          <span class="text-[11px]">{{ initials }}</span>
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../lib/api'
import { clock, fmt, money, signed } from '../lib/format'
import { logout, setSymbol, setTimeframe, state, toast } from '../lib/store'

const router = useRouter()
const timeframes = ['M1', 'M5', 'M15', 'H1', 'H4']
const modes = [
  { id: 'manual', label: 'Manual + AI', hint: 'AI แนะนำ ผู้ใช้กด Buy/Sell เอง' },
  { id: 'semi_auto', label: 'Semi-Auto', hint: 'AI แจ้งสัญญาณ ผู้ใช้อนุมัติ ระบบจัดการ SL/TP' },
  { id: 'full_auto', label: 'Full Auto', hint: 'EA เปิดไม้ตามกฎหลังผ่าน Risk Engine (ต้องปลดล็อก)' },
]

const symbols = computed(() => state.config?.symbols || state.brokers?.symbols || ['XAUUSD'])
const ticker = computed(() => state.live?.ticker)
const account = computed(() => state.live?.account)
const risk = computed(() => state.live?.risk_state)
const mode = computed(() => state.live?.mode || 'manual')
const digits = computed(() => state.live?.analysis?.spec?.digits ?? 2)
const health = computed(() => account.value?.health || 'connecting')
const healthTone = computed(() => (health.value === 'connected' ? 'bg-up' : health.value === 'degraded' ? 'bg-amber-400' : 'bg-down'))
const fullAutoAllowed = computed(
  () => Boolean(state.config?.security?.allow_full_auto && state.config?.security?.full_auto_enabled),
)
const initials = computed(() => (state.user?.email || 'N7').slice(0, 2).toUpperCase())
// The account's role decides what the server will accept; the UI says so rather
// than letting a viewer discover it through 403s.
const role = computed(() => state.user?.role || '')
const roleTone = computed(() => (role.value === 'admin' ? 'chip-up'
  : role.value === 'trader' ? 'chip-warn' : 'chip-down'))
const roleHint = computed(() => ({
  admin: 'จัดการผู้ใช้และเปลี่ยน security posture ได้',
  trader: 'สั่งออเดอร์/เทรน/backtest ได้ — จัดการผู้ใช้ไม่ได้',
  viewer: 'อ่านได้เท่านั้น — ปุ่มที่เปลี่ยนสถานะจะถูกปฏิเสธ',
}[role.value] || ''))

const change = computed(() => {
  const c = state.candles || []
  if (c.length < 2) return 0
  return Number(c[c.length - 1].c) - Number(c[c.length - 2].c)
})
const changePct = computed(() => {
  const c = state.candles || []
  if (c.length < 2) return 0
  return ((Number(c[c.length - 1].c) - Number(c[c.length - 2].c)) / Number(c[c.length - 2].c)) * 100
})

async function switchSymbol(symbol) {
  setSymbol(symbol)
  try {
    await api.post('/api/system/config', {}) // no-op keeps the session warm; symbol is client-side
  } catch {
    /* ignore */
  }
}

async function changeMode(id) {
  try {
    await api.post('/api/trading/mode', { mode: id })
    toast(`Trading mode → ${id.replace('_', ' ')}`, 'success')
    const data = await api.get('/api/trading/state', { silent: true })
    if (data) state.trading = data
  } catch (err) {
    toast(err.message, 'error')
  }
}

function signOut() {
  logout()
  router.push('/login')
}
</script>
