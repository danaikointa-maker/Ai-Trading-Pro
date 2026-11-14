<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Risk Engine</div>
        <div class="panel-sub">มีสิทธิ์ยับยั้งคำสั่งของ AI ได้เสมอ</div>
      </div>
      <span class="chip" :class="risk?.kill_switch_active ? 'chip-down' : 'chip-up'">
        {{ risk?.kill_switch_active ? 'KILL SWITCH' : 'armed' }}
      </span>
    </div>
    <div class="space-y-2.5 px-4 py-3">
      <div v-for="m in meters" :key="m.label">
        <div class="flex items-center justify-between text-[10.5px]">
          <span class="text-slate-300">{{ m.label }}</span>
          <span class="num" :class="m.tone">{{ m.value }}</span>
        </div>
        <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-700">
          <div class="h-full rounded-full transition-all" :class="m.bar" :style="{ width: m.pct + '%' }" />
        </div>
      </div>
    </div>
    <dl class="grid grid-cols-2 gap-x-4 border-t border-ink-700/60 px-4 py-3 text-[11px]">
      <div class="kv"><dt>Open trades</dt><dd>{{ risk?.open_trades ?? 0 }} / {{ risk?.max_trades_allowed ?? 1 }}</dd></div>
      <div class="kv">
        <dt>Consecutive losses</dt>
        <dd :class="streakStopped ? 'text-down font-semibold' : ''">
          {{ risk?.consecutive_losses ?? 0 }} / {{ maxStreak }}
        </dd>
      </div>
      <div class="kv"><dt>Trades today</dt><dd>{{ risk?.trades_today ?? 0 }}</dd></div>
      <div class="kv"><dt>Exposure</dt><dd>{{ fmt(risk?.open_lots, 2) }} lot</dd></div>
      <div class="kv"><dt>Peak equity</dt><dd>{{ money(risk?.peak_equity) }}</dd></div>
      <div class="kv"><dt>Cooldown</dt><dd>{{ risk?.cooldown_until ? clock(risk.cooldown_until) : '—' }}</dd></div>
    </dl>
    <!-- Three losses in a row stop trading and nothing lifts it on a timer. The
         hand-approval button goes through the same gate, so the only ways out are
         a winning trade recorded at the broker, or this release. Say so here —
         otherwise the terminal just looks broken. -->
    <div v-if="streakStopped" class="mx-4 mb-3 rounded-lg border border-down/30 bg-down/10 p-2.5 text-[11px] text-down">
      <div class="font-semibold">หยุดเทรด: ขาดทุนติดกัน {{ risk?.consecutive_losses }} ไม้ (เพดาน {{ maxStreak }})</div>
      <p class="mt-1 text-[10.5px] text-down/90">
        ระบบจะไม่กลับมาเทรดเองเมื่อครบ cooldown — ต้องมีไม้ที่กำไรเข้ามาในบัญชี
        หรือกดปลดด้านล่าง (บันทึก audit) · ปุ่มอนุมัติไม้ด้วยมือก็ถูกกฎนี้บล็อกเช่นกัน
      </p>
      <button class="btn btn-danger mt-2 w-full py-1.5" :disabled="!perms.canTrade || releasing"
              :title="perms.reason" @click="releaseStreak">
        {{ releasing ? 'กำลังปลด…' : 'ปลดการหยุดจากสตรีคขาดทุน' }}
      </button>
    </div>
    <div v-if="risk?.kill_switch_active" class="mx-4 mb-3 rounded-lg border border-down/30 bg-down/10 p-2.5 text-[11px] text-down">
      {{ risk.kill_switch_reason }}
      <button class="btn btn-danger mt-2 w-full py-1.5" :disabled="!perms.canTrade" :title="perms.reason" @click="resetKill">Reset kill switch</button>
    </div>
    <div v-else class="flex gap-2 px-4 pb-3">
      <button class="btn btn-danger flex-1 py-1.5" :disabled="!perms.canTrade" :title="perms.reason" @click="kill(true)">Emergency close all</button>
      <RouterLink to="/risk" class="btn flex-1 py-1.5 text-center">Settings</RouterLink>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { api } from '../lib/api'
import { clock, fmt, money } from '../lib/format'
import { permissions, riskState as risk, state, toast } from '../lib/store'

// Read-only accounts see the buttons disabled — the server refuses them anyway.
const perms = computed(() => permissions.value)
const releasing = ref(false)
const maxStreak = computed(() => state.live?.limits?.max_consecutive_losses ?? 3)
const streakStopped = computed(() => (risk.value?.consecutive_losses ?? 0) >= maxStreak.value)

const limits = computed(() => ({
  daily: state.live?.limits?.max_daily_loss_pct ?? 2.0,
  dd: state.live?.limits?.max_drawdown_pct ?? 10.0,
  exposure: state.live?.limits?.max_exposure_lots ?? 1.0,
}))

const meters = computed(() => {
  const r = risk.value || {}
  const dailyUsed = Math.max(0, -(r.daily_pnl_pct || 0)) / limits.value.daily * 100
  const ddUsed = Math.max(0, -(r.drawdown_pct || 0)) / limits.value.dd * 100
  const expUsed = (r.open_lots || 0) / limits.value.exposure * 100
  return [
    {
      label: `Daily loss · limit ${limits.value.daily}%`,
      value: `${(r.daily_pnl_pct || 0).toFixed(2)}%`,
      pct: Math.min(100, dailyUsed),
      bar: dailyUsed > 80 ? 'bg-down' : dailyUsed > 50 ? 'bg-amber-400' : 'bg-up',
      tone: (r.daily_pnl_pct || 0) < 0 ? 'text-down' : 'text-up',
    },
    {
      label: `Drawdown · limit ${limits.value.dd}%`,
      value: `${(r.drawdown_pct || 0).toFixed(2)}%`,
      pct: Math.min(100, ddUsed),
      bar: ddUsed > 80 ? 'bg-down' : ddUsed > 50 ? 'bg-amber-400' : 'bg-up',
      tone: (r.drawdown_pct || 0) < 0 ? 'text-down' : 'text-up',
    },
    {
      label: `Exposure · limit ${limits.value.exposure} lot`,
      value: `${fmt(r.open_lots, 2)} lot`,
      pct: Math.min(100, expUsed),
      bar: expUsed > 80 ? 'bg-amber-400' : 'bg-gold-400',
      tone: 'text-slate-200',
    },
  ]
})

async function releaseStreak() {
  if (releasing.value) return
  if (!confirm(`ปลดการหยุดจากขาดทุนติดกัน ${risk.value?.consecutive_losses} ไม้?\n`
             + 'ไม้ที่ขาดทุนก่อนหน้านี้จะไม่ถูกนับอีก (P&L เดิมไม่ถูกแก้ และมีบันทึก audit)')) return
  releasing.value = true
  try {
    await api.post('/api/risk/loss-streak/release')
    toast('ปลดแล้ว — ระบบกลับมาพิจารณาสัญญาณตามปกติ', 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    releasing.value = false
  }
}

async function kill(flatten) {
  if (!confirm('ยืนยันหยุดระบบฉุกเฉินและปิดทุกไม้?')) return
  try {
    await api.post('/api/risk/kill-switch', { reason: 'manual emergency stop', flatten })
    toast('Kill switch ทำงาน — ปิดทุกไม้แล้ว', 'warn')
  } catch (err) {
    toast(err.message, 'error')
  }
}
async function resetKill() {
  try {
    await api.del('/api/risk/kill-switch')
    toast('Reset kill switch แล้ว', 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}
</script>
