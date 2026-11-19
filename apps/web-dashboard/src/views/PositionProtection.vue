<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Position Protection</h1>
        <p class="text-[10.5px] text-muted">จัดการ SL ของ position ที่เปิดอยู่ · แยกโหมดป้องกันจากโหมดเปิดออเดอร์</p>
      </div>
      <div class="ml-auto flex flex-wrap gap-1.5">
        <span class="chip chip-warn">{{ data?.profile?.id || 'V1.1' }} · STAGED</span>
        <span class="chip" :class="data?.execution === 'paper' ? 'chip-up' : 'chip-warn'">{{ data?.execution || 'checking' }}</span>
        <button class="btn py-1" :disabled="loading" @click="load">{{ loading ? 'กำลังอ่าน…' : 'Refresh' }}</button>
      </div>
    </header>

    <div class="rounded-lg border border-amber-500/30 bg-amber-950/20 px-3 py-2 text-[10px] leading-relaxed text-amber-100">
      Profile V1.1 ยังไม่เปิด Auto modification · Live Auto Trading ถูกล็อก · Demo apply ยังไม่เปิดจนกว่าจะผ่าน Paper gates และได้รับอนุมัติ
      <span v-if="data?.broker_id" class="num"> · {{ data.broker_id }} · {{ data.account_type }}</span>
    </div>

    <div v-if="error" role="alert" class="rounded-lg border border-down/40 bg-down/10 px-3 py-2 text-[10px] text-down">{{ error }}</div>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section class="panel overflow-hidden">
        <div class="panel-head border-b border-ink-700/60">
          <div><div class="panel-title">Open positions</div><div class="panel-sub">บัญชี {{ data?.broker_id || '—' }} · {{ positions.length }} ไม้ · อ่านจาก adapter ปัจจุบัน</div></div>
          <div class="flex gap-1.5">
            <button class="btn py-1" :disabled="!data || busy" @click="control(data.paused ? 'resume' : 'pause')">{{ data?.paused ? 'Resume' : 'Pause' }}</button>
          </div>
        </div>
        <div v-if="positions.length" class="overflow-x-auto">
          <table class="w-full min-w-[680px] text-left text-[10px]">
            <thead class="bg-ink-900 text-muted"><tr><th class="px-3 py-2">Ticket / Symbol</th><th>Side</th><th>Volume</th><th>Entry</th><th>Broker SL</th><th>TP</th><th>Protection</th></tr></thead>
            <tbody><tr v-for="row in positions" :key="row.position.ticket" class="border-t border-ink-700/60">
              <td class="px-3 py-2"><button class="font-medium text-slate-100 hover:text-gold-300" @click="selectedTicket = row.position.ticket">{{ row.position.ticket }} · {{ row.position.symbol }}</button><div class="text-[8.5px] text-muted">signal {{ row.position.signal_id || 'unlinked' }}</div></td>
              <td :class="row.position.direction === 'up' ? 'text-up' : 'text-down'">{{ row.position.direction === 'up' ? 'BUY' : 'SELL' }}</td>
              <td class="num">{{ fmt(row.position.volume, 2) }}</td><td class="num">{{ fmt(row.position.entry, 3) }}</td>
              <td class="num text-amber-200">{{ row.position.sl ? fmt(row.position.sl, 3) : '—' }}</td><td class="num">{{ row.position.tp ? fmt(row.position.tp, 3) : '—' }}</td>
              <td><span class="chip" :class="latestStatus(row) === 'broker_confirmed' ? 'chip-up' : latestStatus(row) ? 'chip-warn' : ''">{{ latestStatus(row) || 'no event' }}</span></td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="px-4 py-8 text-center text-[10px] text-muted">ไม่มี position เปิดในบัญชีที่ตรวจสอบอยู่</p>
        <div class="border-t border-ink-700/60 px-3 py-2 text-[9px] text-muted">Accepted ≠ broker-confirmed · คำขอที่ไม่ชัดเจนจะล็อกการส่งซ้ำจนกว่าจะ reconcile</div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><div class="panel-title">Protection preview</div><div class="panel-sub">คำนวณจาก fill, initial SL และราคาฝั่งปิดปัจจุบัน</div></div></div>
        <div class="space-y-2 px-3 py-3">
          <label class="block text-[9.5px] text-muted">Position
            <select v-model="selectedTicket" class="input mt-1">
              <option value="">เลือก position</option>
              <option v-for="row in positions" :key="row.position.ticket" :value="row.position.ticket">{{ row.position.ticket }} · {{ row.position.symbol }} · {{ row.position.direction === 'up' ? 'BUY' : 'SELL' }}</option>
            </select>
          </label>
          <div class="grid grid-cols-2 gap-2">
            <label class="text-[9.5px] text-muted">Protection mode
              <select v-model="mode" class="input mt-1" @change="saveMode">
                <option value="MANUAL">MANUAL</option><option value="SEMI_AUTO">SEMI-AUTO</option>
                <option value="FULL_AUTO" disabled>FULL AUTO · locked</option><option value="HYBRID" disabled>HYBRID · locked</option>
              </select>
            </label>
            <label class="text-[9.5px] text-muted">Candidate
              <select v-model="action" class="input mt-1"><option value="break_even">Break even</option><option value="trailing">ATR trailing</option></select>
            </label>
          </div>
          <button class="btn btn-gold w-full py-1.5" :disabled="busy || !selectedTicket" @click="preview">{{ busy ? 'กำลังประเมิน…' : 'Preview SL' }}</button>
          <div v-if="proposal" class="rounded-lg border p-2.5" :class="proposal.status === 'proposed' ? 'border-gold-400/40 bg-gold-400/5' : 'border-amber-700/40 bg-amber-950/15'">
            <div class="flex items-center justify-between"><strong class="text-[10px]" :class="proposal.status === 'proposed' ? 'text-gold-200' : 'text-amber-200'">{{ proposal.status.toUpperCase() }}</strong><span class="text-[8px] text-muted">{{ proposal.profile_status }}</span></div>
            <div class="mt-2 grid grid-cols-2 gap-y-1 text-[9px]">
              <span class="text-muted">Broker SL</span><span class="num text-right">{{ fmt(proposal.current_sl, 3) }}</span>
              <span class="text-muted">Proposed SL</span><span class="num text-right text-amber-200">{{ proposal.proposed_sl ? fmt(proposal.proposed_sl, 3) : '—' }}</span>
              <span class="text-muted">Initial R (price)</span><span class="num text-right">{{ proposal.initial_r_price ? fmt(proposal.initial_r_price, 3) : '—' }}</span>
              <span class="text-muted">Close-side price</span><span class="num text-right">{{ fmt(proposal.current_close_price, 3) }}</span>
            </div>
            <ul v-if="proposal.blockers?.length" class="mt-2 list-inside list-disc text-[8.5px] text-amber-200"><li v-for="item in proposal.blockers" :key="item">{{ item }}</li></ul>
            <button v-if="proposal.status === 'proposed' && data?.execution === 'paper'" class="btn btn-gold mt-2 w-full py-1.5" :disabled="busy" @click="apply">Apply to PAPER</button>
          </div>
          <p class="text-[8.5px] leading-relaxed text-muted">Manual/SEMI-AUTO Apply ใช้ได้เฉพาะ Paper adapter ในเฟสนี้ · คำขอจะตรวจ version, tick, stops/freeze, monotonic SL และ broker snapshot อีกครั้ง</p>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">Protection performance analyzer</div><div class="panel-sub">แยก telemetry ออกจากหลักฐานผลลัพธ์เชิงสาเหตุ</div></div><button class="btn py-1" :disabled="busy" @click="loadAnalyzer">Load</button></div>
      <div class="px-3 py-3 text-[9.5px] leading-relaxed text-muted">
        <p v-if="analyzer">สถานะ: <span class="text-amber-200">{{ analyzer.status }}</span> · {{ analyzer.causal_comparison }}</p>
        <p v-else>การนับคำขอแก้ SL ไม่พิสูจน์ว่าลด drawdown หรือคงกำไรได้ ต้องเทียบ entry ชุดเดียวกันและข้อมูลราคา/cost เดียวกันแบบ paired replay แล้วแยก REAL ticks กับ synthetic/replay ให้ชัด</p>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><div><div class="panel-title">Calculator · read only</div><div class="panel-sub">ใช้เครื่องคำนวณเดิม ไม่มี endpoint ส่งคำสั่ง</div></div></div>
      <div class="p-3"><PointsCalculator /></div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import PointsCalculator from '../components/PointsCalculator.vue'
import { api } from '../lib/api'
import { fmt } from '../lib/format'
import { permissions, toast } from '../lib/store'

const data = ref(null)
const proposal = ref(null)
const analyzer = ref(null)
const selectedTicket = ref('')
const mode = ref('MANUAL')
const action = ref('break_even')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const positions = computed(() => data.value?.positions || [])
let timer

async function load() {
  loading.value = true; error.value = ''
  try {
    const result = await api.get('/api/position-protection')
    data.value = result
    mode.value = result.mode || 'MANUAL'
    if (!positions.value.some(row => String(row.position.ticket) === String(selectedTicket.value))) {
      selectedTicket.value = positions.value[0]?.position.ticket || ''
    }
  } catch (err) { data.value = null; error.value = err.message || 'อ่านข้อมูล Position Protection ไม่สำเร็จ' }
  finally { loading.value = false }
}
async function preview() {
  if (!selectedTicket.value || busy.value) return
  busy.value = true; proposal.value = null; error.value = ''
  try { proposal.value = await api.post('/api/position-protection/preview', { ticket: String(selectedTicket.value), action: action.value, mode: mode.value }) }
  catch (err) { error.value = err.message || 'ประเมิน SL ไม่สำเร็จ' }
  finally { busy.value = false }
}
async function apply() {
  if (!proposal.value?.position_version || !Number.isFinite(Number(proposal.value.proposed_sl))) return
  if (!permissions.value.canTrade || !confirm(`ยืนยัน Apply SL ${fmt(proposal.value.proposed_sl, 3)} กับ Paper position #${selectedTicket.value}?`)) return
  busy.value = true
  try {
    await api.post('/api/position-protection/apply', {
      ticket: String(selectedTicket.value), action: action.value, mode: mode.value,
      expected_position_version: proposal.value.position_version,
      expected_sl: Number(proposal.value.proposed_sl), idempotency_key: crypto.randomUUID(),
    })
    toast('ส่งคำขอ Paper แล้ว · รอตรวจ broker snapshot', 'success')
    proposal.value = null
    await load()
  } catch (err) { error.value = err.message || 'Apply ไม่สำเร็จ' }
  finally { busy.value = false }
}
async function saveMode() {
  if (!['MANUAL', 'SEMI_AUTO'].includes(mode.value)) { mode.value = 'MANUAL'; return }
  try { await api.put('/api/position-protection/mode', { mode: mode.value }) }
  catch (err) { error.value = err.message || 'บันทึกโหมดไม่สำเร็จ'; mode.value = 'MANUAL' }
}
async function control(actionName) {
  if (busy.value) return
  busy.value = true
  try { await api.post(`/api/position-protection/${actionName}`, { reason: 'dashboard operator' }); await load() }
  catch (err) { error.value = err.message || 'เปลี่ยนสถานะไม่ได้' }
  finally { busy.value = false }
}
async function loadAnalyzer() {
  try { analyzer.value = await api.get('/api/position-protection/analyzer') }
  catch (err) { error.value = err.message || 'อ่าน Analyzer ไม่สำเร็จ' }
}
function latestStatus(row) { return row.events?.at(-1)?.status || '' }
onMounted(() => { void load(); timer = window.setInterval(load, 5000) })
onUnmounted(() => { if (timer) window.clearInterval(timer) })
</script>
