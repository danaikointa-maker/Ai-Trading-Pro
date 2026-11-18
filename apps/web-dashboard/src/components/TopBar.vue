<template>
  <header class="sticky top-0 z-30 border-b border-ink-700/70 bg-ink-950/85 backdrop-blur">
    <div class="flex w-full flex-wrap items-center gap-x-2 gap-y-1 px-2 py-1.5 sm:px-3">
      <button id="sidebar-toggle" type="button" class="tool-btn" :aria-expanded="sidebarOpen" :aria-controls="sidebarTarget"
              :title="sidebarOpen ? 'ซ่อนเมนูซ้าย' : 'แสดงเมนูซ้าย'" :aria-label="sidebarOpen ? 'ซ่อนเมนูซ้าย' : 'แสดงเมนูซ้าย'" @click="toggleSidebar">
        <ToolIcon :name="sidebarOpen ? 'sidebarClose' : 'sidebarOpen'" />
      </button>
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
        <span class="chip num" :title="`Spread ${fmt(ticker.spread_points, 0)} points`" :aria-label="`Spread ${fmt(ticker.spread_points, 0)} points`"><ToolIcon name="width" />{{ fmt(ticker.spread_points, 0) }}</span>
      </div>

      <div class="ml-auto flex flex-wrap items-center gap-1.5">
        <div class="hidden items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 p-0.5 md:flex">
          <TimeframePicker />
        </div>

        <div class="hidden items-center gap-1 sm:flex" title="Equity · มูลค่าบัญชี" aria-label="Equity">
          <ToolIcon name="wallet" />
          <div class="num text-[13px] font-semibold text-slate-100">{{ money(account?.equity) }}</div>
        </div>
        <div class="hidden items-center gap-1 sm:flex" title="กำไร/ขาดทุนวันนี้" aria-label="กำไร/ขาดทุนวันนี้">
          <ToolIcon name="pnl" />
          <div class="num text-[13px] font-semibold" :class="(risk?.daily_pnl || 0) >= 0 ? 'text-up' : 'text-down'">
            {{ money(risk?.daily_pnl) }}
          </div>
        </div>

        <div class="flex items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 p-0.5">
          <button
            v-for="m in modes"
            :key="m.id"
            class="rounded-md px-2 py-1 text-[10.5px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
            :class="mode === m.id ? 'bg-gold-500/15 text-gold-400 ring-1 ring-gold-500/30' : 'text-muted hover:text-slate-200'"
            :disabled="modeChanging || Boolean(modeUnavailable(m.id))"
            :title="modeUnavailable(m.id) || m.hint" :aria-label="m.hint" :aria-pressed="mode === m.id"
            @click="changeMode(m.id)"
          >
            {{ m.label }}<ToolIcon v-if="m.id === 'full_auto' && !fullAutoAllowed" name="lock" class="ml-1 inline-block !h-3 !w-3 opacity-60" />
          </button>
        </div>

        <div class="flex h-8 w-6 items-center justify-center" role="status" :title="`สถานะการเชื่อมต่อ: ${health}`" :aria-label="`สถานะการเชื่อมต่อ: ${health}`">
          <span class="h-2 w-2 rounded-full" :class="healthTone" />
        </div>

        <div class="hidden items-center gap-1 lg:flex" title="Market clock · เวลาของ runtime" aria-label="Market clock">
          <ToolIcon name="clock" />
          <div class="num text-[12px] text-slate-300">{{ clock(state.live?.virtual_time) }}</div>
        </div>

        <span v-if="role" class="chip" :class="roleTone" :title="`${role}: ${roleHint}`" :aria-label="`${role}: ${roleHint}`"><ToolIcon name="shield" /></span>

        <button class="tool-btn" title="ออกจากระบบ" aria-label="ออกจากระบบ" @click="signOut">
          <ToolIcon name="logout" />
        </button>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { clock, fmt, money, signed } from '../lib/format'
import { changeTradingMode, logout, mode, modeChanging, modeUnavailable, setSymbol, state, toast } from '../lib/store'
import TimeframePicker from './TimeframePicker.vue'
import ToolIcon from './ToolIcon.vue'
import { sidebarOpen, sidebarTarget, toggleSidebar } from '../lib/sidebar'

const router = useRouter()
const modes = [
  { id: 'manual', label: 'MAN', hint: 'Manual + AI · AI แนะนำ ผู้ใช้กด Buy/Sell เอง' },
  { id: 'semi_auto', label: 'SEMI', hint: 'Semi-Auto · AI แจ้งสัญญาณ ผู้ใช้อนุมัติ ระบบจัดการ SL/TP' },
  { id: 'full_auto', label: 'AUTO', hint: 'Full Auto · EA เปิดไม้ตามกฎหลังผ่าน Risk Engine (ต้องปลดล็อก)' },
]

const symbols = computed(() => state.config?.symbols || state.brokers?.symbols || ['XAUUSD'])
const ticker = computed(() => state.live?.ticker)
const account = computed(() => state.live?.account)
const risk = computed(() => state.live?.risk_state)
const digits = computed(() => state.live?.analysis?.spec?.digits ?? 2)
const health = computed(() => account.value?.health || 'connecting')
const healthTone = computed(() => (health.value === 'connected' ? 'bg-up' : health.value === 'degraded' ? 'bg-amber-400' : 'bg-down'))
const fullAutoAllowed = computed(
  () => Boolean(state.config?.security?.allow_full_auto && state.config?.security?.full_auto_enabled),
)
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
}

async function changeMode(id) {
  try {
    await changeTradingMode(id)
    toast(`Trading mode → ${id.replace('_', ' ')}`, 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}

function signOut() {
  logout()
  router.push('/login')
}
</script>
