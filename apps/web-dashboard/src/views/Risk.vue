<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Risk Engine</h1>
        <p class="text-[11px] text-muted">กำหนดกรอบความเสี่ยงที่ AI ต้องอยู่ภายใต้ — Risk Engine มีสิทธิ์ยับยั้งทุกคำสั่ง</p>
      </div>
      <div class="ml-auto flex gap-1.5">
        <span class="chip" :class="risk?.kill_switch_active ? 'chip-down' : 'chip-up'">{{ risk?.kill_switch_active ? 'kill switch active' : 'armed' }}</span>
        <button class="btn btn-gold py-1.5" :disabled="saving" @click="save">{{ saving ? 'saving…' : 'Save risk settings' }}</button>
      </div>
    </header>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div class="space-y-3">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Limits</div><span class="panel-sub">ค่าเริ่มต้นสำหรับโหมดทดลอง</span></div>
          <div class="grid gap-3 px-4 py-3 sm:grid-cols-2 lg:grid-cols-3">
            <label v-for="f in numberFields" :key="f.key" class="block">
              <span class="label">{{ f.label }}</span>
              <input v-model.number="form[f.key]" type="number" :step="f.step" :min="f.min" class="input mt-1 num" />
              <span class="mt-1 block text-[9.5px] leading-snug text-muted">{{ f.hint }}</span>
            </label>
            <label class="flex items-center gap-2 self-end rounded-lg border border-ink-700 bg-ink-900 px-3 py-2">
              <input v-model="form.news_lockout_enabled" type="checkbox" class="accent-gold-400" />
              <span class="text-[11px] text-slate-300">ระงับเปิดไม้ช่วงข่าวแรง</span>
            </label>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Execution policy</div><span class="chip">{{ modeLabel }}</span></div>
          <div class="px-4 py-3">
            <ModeSwitch />
            <div class="mt-3 rounded-lg border border-ink-700 bg-ink-900/60 p-3 text-[10.5px] leading-relaxed text-muted">
              <p class="mb-1 text-slate-300"><strong>Full Auto</strong> ต้องผ่านทุกเงื่อนไข:</p>
              <ul class="list-inside list-disc space-y-0.5">
                <li v-for="r in fullAuto.requirements" :key="r">{{ r }}</li>
              </ul>
              <p class="mt-1.5">
                ENV: <span class="num" :class="fullAuto.allowed_by_env ? 'text-up' : 'text-down'">NO7_ALLOW_FULL_AUTO={{ fullAuto.allowed_by_env }}</span>
                · risk toggle: <span class="num" :class="fullAuto.enabled ? 'text-up' : 'text-muted'">{{ fullAuto.enabled }}</span>
              </p>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Ladder preview</div><span class="chip">{{ plan?.target_mode || 'adaptive' }}</span></div>
          <div v-if="plan" class="px-4 py-3">
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Entry" :value="fmt(plan.entry, digits)" />
              <Stat label="Stop" :value="fmt(plan.sl, digits)" tone="text-down" :hint="`${fmt(plan.sl_points,0)} pts`" />
              <Stat label="Lot" :value="fmt(plan.lot, 2)" :hint="`risk ${money(plan.risk_amount)}`" />
              <Stat label="Net R:R" :value="fmt(plan.reward_risk_net, 2)" tone="text-gold-400" />
            </div>
            <table class="table-base mt-3">
              <thead><tr><th>Level</th><th>Points</th><th>Price</th><th>Close %</th><th>Lot</th><th>Feasible</th></tr></thead>
              <tbody>
                <tr v-for="p in plan.partials" :key="p.level">
                  <td>TP{{ p.level }}</td>
                  <td class="num">{{ fmt(p.points, 0) }}</td>
                  <td class="num">{{ fmt(p.price, digits) }}</td>
                  <td class="num">{{ fmt(p.close_pct, 0) }}%</td>
                  <td class="num">{{ fmt(p.volume, 2) }}</td>
                  <td><span class="chip" :class="p.feasible ? 'chip-up' : 'chip-warn'">{{ p.feasible ? 'ok' : 'blocked' }}</span></td>
                </tr>
              </tbody>
            </table>
            <p class="mt-2 text-[10px] leading-relaxed text-muted">
              ระยะ TP เลือกจาก ATR + พื้นที่ว่างก่อนถึงแนวต้าน/แนวรับ และบังคับช่วง {{ fmt(limits.min_points, 0) }}–{{ fmt(limits.max_points, 0) }} points
              · ตรวจ Lot Step ก่อนแบ่งปิดทุกครั้ง
            </p>
          </div>
          <p v-else class="px-4 py-6 text-center text-[11px] text-muted">ยังไม่มีแผนที่คำนวณได้ในรอบนี้</p>
        </section>

        <PointsCalculator />
      </div>

      <div class="space-y-3">
        <RiskPanel />
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Risk math</div></div>
          <div class="space-y-2 px-4 py-3 text-[10.5px] leading-relaxed text-muted">
            <p><span class="text-slate-300">Lot = (Equity × Risk% ÷ 100) ÷ (SL points × value/point/lot)</span></p>
            <p>ตัวอย่าง: equity {{ money(risk?.equity) }}, risk {{ fmt(form.risk_per_trade_pct, 2) }}%, SL {{ fmt(plan?.sl_points || 400, 0) }} pts,
              XAUUSD value/point/lot ≈ $1 → lot ≈ {{ computedLot }}</p>
            <p>ห้ามใช้ Martingale / Grid เพิ่มไม้ขาดทุน / Average Down — ระบบไม่อนุญาตใน Risk Engine</p>
            <div class="divider"></div>
            <p>Daily kill switch: เมื่อขาดทุนถึง {{ fmt(form.max_daily_loss_pct, 2) }}% ระบบหยุดเปิดไม้ใหม่และต้องปลดล็อกด้วยมือ</p>
          </div>
        </section>
        <section class="panel border-amber-400/25">
          <div class="panel-head"><div class="panel-title">Legal & safety</div><span class="chip chip-warn">read me</span></div>
          <p class="px-4 py-3 text-[10px] leading-relaxed text-muted">
            Connext ระบุเองว่า FSA (St. Vincent & the Grenadines) ไม่ได้กำกับกิจกรรม Forex โดยตรง และ ธปท. เตือนเรื่องแพลตฟอร์ม
            Forex สำหรับเก็งกำไรและผู้ให้บริการที่ไม่ได้รับอนุญาต จึงควรใช้ Demo และตรวจสอบกฎหมาย/ความคุ้มครองก่อนฝากเงินจริง
          </p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import ModeSwitch from '../components/ModeSwitch.vue'
import PointsCalculator from '../components/PointsCalculator.vue'
import RiskPanel from '../components/RiskPanel.vue'
import Stat from '../components/Stat.vue'
import { api } from '../lib/api'
import { fmt, money } from '../lib/format'
import { riskState as risk, state, toast } from '../lib/store'

const saving = ref(false)
const view = ref(null)
const form = reactive({
  risk_per_trade_pct: 0.5,
  max_daily_loss_pct: 2,
  max_weekly_loss_pct: 5,
  max_drawdown_pct: 10,
  max_open_trades: 1,
  max_consecutive_losses: 3,
  cooldown_minutes: 20,
  max_spread_points: 60,
  min_reward_risk: 1.3,
  max_exposure_lots: 1,
  news_lockout_enabled: true,
  max_weekly_trades: 60,
})

const numberFields = [
  { key: 'risk_per_trade_pct', label: 'Risk per trade %', step: 0.05, min: 0.05, hint: 'ใช้คำนวณ Lot จากระยะ SL' },
  { key: 'max_daily_loss_pct', label: 'Max daily loss %', step: 0.1, min: 0.2, hint: 'Daily kill switch' },
  { key: 'max_weekly_loss_pct', label: 'Max weekly loss %', step: 0.5, min: 0.5, hint: 'หยุดทั้งสัปดาห์เมื่อถึง' },
  { key: 'max_drawdown_pct', label: 'Max drawdown %', step: 0.5, min: 1, hint: 'นับจาก peak equity' },
  { key: 'max_open_trades', label: 'Max open trades', step: 1, min: 1, hint: 'จำนวนไม้เปิดพร้อมกัน' },
  { key: 'max_consecutive_losses', label: 'Max consecutive losses', step: 1, min: 1, hint: 'จากนั้นเข้าสู่ cooldown' },
  { key: 'cooldown_minutes', label: 'Cooldown (minutes)', step: 5, min: 1, hint: 'พักหลังขาดติดกัน' },
  { key: 'max_spread_points', label: 'Max spread (points)', step: 5, min: 5, hint: 'ไม่เปิดไม้เมื่อ spread สูง' },
  { key: 'min_reward_risk', label: 'Min net R:R', step: 0.05, min: 1, hint: 'หลังหัก spread + commission' },
  { key: 'max_exposure_lots', label: 'Max exposure (lots)', step: 0.1, min: 0.01, hint: 'รวมทุกไม้' },
  { key: 'max_weekly_trades', label: 'Max trades / week', step: 1, min: 1, hint: 'กัน overtrading' },
]

const limits = computed(() => view.value?.settings || {
  min_points: 500, max_points: 1000, fixed_points: [500, 750, 1000],
})
const plan = computed(() => state.live?.signal?.plan || null)
const digits = computed(() => state.live?.analysis?.spec?.digits ?? 2)
const modeLabel = computed(() => ({ manual: 'Manual + AI', semi_auto: 'Semi-Auto', full_auto: 'Full Auto' }[state.live?.mode] || '—'))
const fullAuto = computed(() => view.value?.full_auto || { enabled: false, allowed_by_env: false, requirements: [] })
const computedLot = computed(() => {
  const eq = risk.value?.equity || 10000
  const sl = plan.value?.sl_points || 400
  const perPoint = 1
  return fmt((eq * (form.risk_per_trade_pct / 100)) / (sl * perPoint), 2)
})

async function load() {
  try {
    view.value = await api.get('/api/risk/settings')
    Object.keys(form).forEach((k) => {
      if (view.value.settings?.limits?.[k] !== undefined) form[k] = view.value.settings.limits[k]
    })
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function save() {
  saving.value = true
  try {
    const payload = { limits: { ...form } }
    await api.put('/api/risk/settings', payload)
    toast('บันทึกการตั้งค่า risk แล้ว', 'success')
    await load()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
