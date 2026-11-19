<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Open Positions</div>
        <div class="panel-sub" role="status">{{ panelStatus }}</div>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <select v-if="readOnlyAccounts.length" v-model="selectedAccountId" class="input max-w-[220px] py-1 text-[10px]"
                aria-label="บัญชี MT5 สำหรับอ่าน positions">
          <option value="">Runtime / simulator</option>
          <option v-for="account in readOnlyAccounts" :key="account.id" :value="account.id">
            {{ account.label }} · {{ account.server }} · {{ account.login }}
          </option>
        </select>
        <a v-else href="/brokers" class="btn py-1 text-[10px]">ผูก MT5 ใน Brokers</a>
        <button v-if="selectedAccountId" class="btn py-1 text-[10px]" :disabled="readOnlyLoading" @click="fetchBrokerPositions">
          {{ readOnlyLoading ? 'กำลังอ่าน…' : 'ดึงข้อมูล MT5' }}
        </button>
        <button v-else class="btn py-1 text-[10px]" :disabled="!positionsAvailable || !positions.length || !permissions.canTrade" :title="permissions.reason" @click="closeAll">Close all</button>
      </div>
    </div>
    <div class="overflow-x-auto">
      <table class="table-base">
        <thead>
          <tr>
            <th>Ticket</th><th>Symbol</th><th>Side</th><th>Lot</th><th>Entry</th><th>SL</th><th>TP</th>
            <th>Price</th><th v-if="!selectedAccountId">Points</th><th>P&amp;L</th>
            <th v-if="!selectedAccountId">BE</th><th v-if="!selectedAccountId"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in displayPositions" :key="p.ticket" class="hover:bg-ink-800/50">
            <td class="num text-[11px] text-muted">{{ p.ticket }}</td>
            <td class="text-[11.5px]">{{ p.symbol }}</td>
            <td><span class="chip" :class="p.direction === 'up' ? 'chip-up' : 'chip-down'">{{ p.direction === 'up' ? 'BUY' : 'SELL' }}</span></td>
            <td class="num">{{ fmt(p.volume, 2) }}</td>
            <td class="num">{{ fmt(p.entry, 2) }}</td>
            <td class="num text-down">{{ fmt(p.sl, 2) }}</td>
            <td class="num text-up">{{ fmt(p.tp, 2) }}</td>
            <td class="num">{{ fmt(p.current_price, 2) }}</td>
            <td v-if="!selectedAccountId" class="num" :class="p.points >= 0 ? 'text-up' : 'text-down'">{{ fmt(p.points, 0) }}</td>
            <td class="num" :class="p.unrealized >= 0 ? 'text-up' : 'text-down'">{{ money(p.unrealized) }}</td>
            <td v-if="!selectedAccountId"><span class="chip" :class="p.breakeven_done ? 'chip-up' : ''">{{ p.breakeven_done ? 'BE' : '—' }}</span></td>
            <td v-if="!selectedAccountId" class="text-right">
              <button class="btn px-2 py-1 text-[10.5px]" :disabled="!permissions.canTrade" :title="permissions.reason" @click="close(p.ticket)">Close</button>
            </td>
          </tr>
          <tr v-if="selectedAccountId && readOnlyError">
            <td :colspan="selectedAccountId ? 9 : 12" class="py-6 text-center text-[11.5px] text-warn">{{ readOnlyError }}</td>
          </tr>
          <tr v-else-if="selectedAccountId && !readOnlySnapshot">
            <td colspan="9" class="py-6 text-center text-[11.5px] text-muted">กด “ดึงข้อมูล MT5” เพื่ออ่านไม้และ SL/TP จากบัญชีที่ผูกใน Brokers</td>
          </tr>
          <tr v-else-if="!selectedAccountId && !positionsAvailable">
            <td colspan="12" class="py-6 text-center text-[11.5px] text-warn">ไม่ทราบ exposure ปัจจุบัน — ข้อมูลขาดหาย หมดอายุ หรือยังยืนยันเจ้าของบัญชีไม่ได้ ไม่ได้หมายความว่าไม่มีไม้เปิดอยู่</td>
          </tr>
          <tr v-else-if="!displayPositions.length">
            <td :colspan="selectedAccountId ? 9 : 12" class="py-6 text-center text-[11.5px] text-muted">ยังไม่มีไม้ที่เปิดอยู่ในแหล่งข้อมูลนี้</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../lib/api'
import { fmt, money } from '../lib/format'
import { closeAllFeedback, closeFeedback } from '../lib/close-results'
import { permissions, positions, positionsAvailable, toast } from '../lib/store'

const readOnlyAccounts = ref([])
const selectedAccountId = ref('')
const readOnlySnapshot = ref(null)
const readOnlyLoading = ref(false)
const readOnlyError = ref('')
const displayPositions = computed(() => selectedAccountId.value
  ? (readOnlySnapshot.value?.positions || []) : positions.value)
const panelStatus = computed(() => {
  if (selectedAccountId.value) {
    const snapshot = readOnlySnapshot.value
    return snapshot
      ? `MT5 Demo อ่านอย่างเดียว · ${snapshot.count} ไม้ · ${new Date(snapshot.fetched_at * 1000).toLocaleTimeString()}`
      : 'เลือกบัญชี MT5 ที่เชื่อมใน Brokers แล้วกดดึงข้อมูล'
  }
  return positionsAvailable.value ? `Runtime / simulator · ${positions.value.length} ไม้ · ข้อมูลยืนยันล่าสุด` : 'Runtime / simulator · ยืนยันสถานะ positions ไม่ได้หรือข้อมูลหมดอายุ'
})

onMounted(loadReadOnlyAccounts)
watch(selectedAccountId, () => {
  readOnlySnapshot.value = null
  readOnlyError.value = ''
})

async function loadReadOnlyAccounts() {
  try {
    const response = await api.get('/api/broker-accounts', { silent: true })
    readOnlyAccounts.value = (response?.accounts || []).filter((account) =>
      account.provider === 'mt5' && account.account_type === 'demo'
      && account.connection_status === 'ready_read_only' && account.can_view)
  } catch {
    readOnlyAccounts.value = []
  }
}

async function fetchBrokerPositions() {
  if (!selectedAccountId.value || readOnlyLoading.value) return
  const requestedAccountId = selectedAccountId.value
  readOnlyLoading.value = true
  readOnlySnapshot.value = null
  readOnlyError.value = ''
  try {
    const response = await api.get(`/api/broker-accounts/${encodeURIComponent(requestedAccountId)}/positions`)
    if (selectedAccountId.value !== requestedAccountId) return
    if (response?.read_only !== true || response?.execution_enabled !== false || !Array.isArray(response?.positions)) {
      throw new Error('ข้อมูล MT5 ไม่ผ่านการตรวจสอบบัญชีอ่านอย่างเดียว')
    }
    readOnlySnapshot.value = response
  } catch (err) {
    if (selectedAccountId.value === requestedAccountId) {
      readOnlyError.value = err.message || 'อ่านข้อมูล MT5 ไม่สำเร็จ — ตรวจการเชื่อมต่อในหน้า Brokers'
    }
  } finally {
    readOnlyLoading.value = false
  }
}

async function close(ticket) {
  if (!positionsAvailable.value || !permissions.value.canTrade) return
  try {
    const res = await api.post('/api/trading/close', { ticket })
    const feedback = closeFeedback(res)
    toast(feedback.message, feedback.type)
  } catch (err) {
    const feedback = closeFeedback(err.detail)
    toast(feedback.message, feedback.type)
  }
}
async function closeAll() {
  if (!positionsAvailable.value || !permissions.value.canTrade || !positions.value.length) return
  if (!confirm('ปิดทุกไม้ที่เปิดอยู่?')) return
  try {
    const res = await api.post('/api/trading/close-all')
    const feedback = closeAllFeedback(res)
    toast(feedback.message, feedback.type)
  } catch (err) {
    const feedback = closeAllFeedback()
    toast(feedback.message, feedback.type)
  }
}
</script>
