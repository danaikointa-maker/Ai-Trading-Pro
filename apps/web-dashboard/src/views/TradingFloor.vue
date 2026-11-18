<template>
  <div class="space-y-4">
    <header class="rounded-xl border border-violet-500/30 bg-violet-500/10 p-4 sm:p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h1 class="text-xl font-semibold text-slate-100">AI Trading Floor</h1>
        <RouterLink to="/" class="btn">เปิด Trading Terminal →</RouterLink>
      </div>
      <p class="mt-3 text-base font-semibold text-violet-200">{{ verdict }}</p>
      <p class="mt-1 break-words text-sm text-slate-300">{{ decisionReason }}</p>
    </header>

    <div class="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <section class="panel min-w-0 overflow-hidden" aria-label="กราฟราคา">
        <PriceChart />
      </section>
      <section aria-labelledby="officer-heading">
        <h2 id="officer-heading" class="mb-1 text-base font-semibold">Officer Team</h2>
        <p class="mb-3 text-xs text-muted">ผลประเมินจาก Trading Runtime</p>
        <ol class="space-y-2">
          <li v-for="(officer, index) in officers" :key="officer.name">
            <details class="panel px-3 py-2.5">
              <summary class="cursor-pointer rounded text-sm text-slate-100 focus-visible:outline-violet-400">
                <span aria-hidden="true" class="mx-1 inline-grid h-7 w-7 place-items-center rounded-full bg-violet-500/15 text-xs font-semibold text-violet-200">{{ index + 1 }}</span>
                <span class="font-semibold">{{ officer.name }}</span>
                <span class="ml-2 text-xs text-violet-200">{{ officer.status }}</span>
              </summary>
              <p class="mt-2 break-words text-xs leading-relaxed text-slate-300">{{ officer.detail }}</p>
              <RouterLink :to="officer.link" class="mt-2 inline-block text-xs text-violet-200 underline">ดู{{ officer.linkLabel }} →</RouterLink>
            </details>
          </li>
        </ol>
      </section>
    </div>

    <section class="panel p-4">
      <h2 class="panel-title">แผนเทรด</h2>
      <dl v-if="plan && !stale && !expired" class="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div v-for="[label, value] in levels" :key="label">
          <dt class="label">{{ label }}</dt>
          <dd class="num mt-1 text-sm text-slate-100">{{ value }}</dd>
        </div>
      </dl>
      <p v-else class="mt-2 text-sm text-muted">{{ stale || expired ? 'รอข้อมูลแผนรอบใหม่' : 'ยังไม่มีแผนเทรดสำหรับรอบนี้' }}</p>
    </section>
    <PositionsTable read-only />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import PriceChart from '../components/PriceChart.vue'
import PositionsTable from '../components/PositionsTable.vue'
import { fmt } from '../lib/format'
import { state } from '../lib/store'

const live = computed(() => state.live?.symbol === state.symbol ? state.live : null)
const analysis = computed(() => live.value?.analysis)
const signal = computed(() => live.value?.signal)
const gate = computed(() => live.value?.gate)
const plan = computed(() => signal.value?.plan)
const expired = computed(() => {
  const expiry = signal.value?.expires_at
  return ['mt5', 'mt5-live'].includes(live.value?.feed)
    && expiry > 0 && state.positionNow >= expiry * 1000
})
const stale = computed(() => !state.connected || state.serverUnreachable || live.value?.ticker_stale
  || state.positionNow - state.lastLiveAt > 10000 || analysis.value?.data_quality?.ok === false)

const verdict = computed(() => {
  if (!live.value) return 'รอข้อมูลจากระบบเทรด'
  if (stale.value) return 'พักการประเมิน · ข้อมูลยังไม่พร้อม'
  if (expired.value) return 'รอการวิเคราะห์รอบใหม่ · สัญญาณหมดอายุ'
  if (gate.value?.allow === false || signal.value?.readiness === 'BLOCKED') return 'ระบบระงับการเข้าเทรด'
  if (!signal.value) return 'กำลังรอผลวิเคราะห์'
  if (signal.value.executed_order_id) return 'ระบบมีคำสั่งที่เชื่อมกับสัญญาณนี้แล้ว'
  if (signal.value.readiness === 'READY' && gate.value?.allow === true
      && ['BUY', 'SELL'].includes(signal.value.action)) return 'มีแผนให้ตรวจสอบ · ' + signal.value.action
  return 'รอเงื่อนไขเข้าเทรด'
})

const decisionReason = computed(() => {
  if (!live.value) return 'ข้อมูลจะแสดงเมื่อได้รับผลประเมินจาก Trading Runtime'
  if (stale.value) return analysis.value?.data_quality?.reason || 'กำลังรอข้อมูลราคาหรือการเชื่อมต่อล่าสุด'
  if (expired.value) return 'กำลังรอผลประเมินรอบถัดไป'
  return gate.value?.blockers?.[0] || signal.value?.readiness_reason || signal.value?.blockers?.[0] || ''
})

const officers = computed(() => [
  {
    name: 'Market Analyst', link: '/zones', linkLabel: 'แนวรับ–แนวต้าน',
    status: analysis.value ? (stale.value ? 'ข้อมูลรอบล่าสุด' : 'มีผลวิเคราะห์') : 'รอข้อมูล',
    detail: analysis.value?.regime?.regime?.replaceAll('_', ' ') || 'รอข้อมูลโครงสร้างตลาด',
  },
  {
    name: 'Strategy Officer', link: '/forecast', linkLabel: 'ผลวิเคราะห์',
    status: stale.value || expired.value ? 'รอผลประเมินรอบใหม่' : signal.value?.action?.replaceAll('_', ' ') || 'รอผลประเมิน',
    detail: [signal.value?.strategy?.replaceAll('_', ' '), signal.value?.readiness_reason].filter(Boolean).join(' · ')
      || 'รอผลประเมินกลยุทธ์',
  },
  {
    name: 'Risk Officer', link: '/risk', linkLabel: 'ความเสี่ยง',
    status: stale.value ? 'รอข้อมูลล่าสุด' : gate.value?.allow === true ? 'ผ่านการประเมินรอบล่าสุด'
      : gate.value?.allow === false ? 'ระงับแผน' : 'รอ Risk Engine',
    detail: [...(gate.value?.blockers || []), ...(gate.value?.warnings || [])].join(' · ')
      || 'แสดงผล Risk Gate ของรอบการประเมินล่าสุด',
  },
  {
    name: 'Execution Officer', link: '/trades', linkLabel: 'ประวัติคำสั่ง',
    status: signal.value?.executed_order_id ? 'มีคำสั่งเชื่อมโยงแล้ว' : 'ติดตามผลคำสั่ง',
    detail: signal.value?.executed_order_id ? 'Order ' + signal.value.executed_order_id
      : 'ตรวจคำสั่งและการอนุมัติผ่าน Trading Terminal',
  },
])

const levels = computed(() => {
  const digits = analysis.value?.spec?.digits ?? 2
  return [
    ['Entry', fmt(plan.value?.entry, digits)],
    ['Stop Loss', fmt(plan.value?.sl, digits)],
    ['Take Profit 1', fmt(plan.value?.tp1, digits)],
    ['Net R:R', fmt(plan.value?.reward_risk_net, 2)],
  ]
})
</script>
