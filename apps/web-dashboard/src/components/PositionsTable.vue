<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Open Positions</div>
        <div class="panel-sub">{{ positions.length }} ไม้ · จัดการ SL/TP อัตโนมัติโดย Risk Engine</div>
      </div>
      <button class="btn py-1" :disabled="!positions.length" @click="closeAll">Close all</button>
    </div>
    <div class="overflow-x-auto">
      <table class="table-base">
        <thead>
          <tr>
            <th>Ticket</th><th>Symbol</th><th>Side</th><th>Lot</th><th>Entry</th><th>SL</th><th>TP</th>
            <th>Price</th><th>Points</th><th>P&L</th><th>BE</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in positions" :key="p.ticket" class="hover:bg-ink-800/50">
            <td class="num text-[11px] text-muted">{{ p.ticket }}</td>
            <td class="text-[11.5px]">{{ p.symbol }}</td>
            <td><span class="chip" :class="p.direction === 'up' ? 'chip-up' : 'chip-down'">{{ p.direction === 'up' ? 'BUY' : 'SELL' }}</span></td>
            <td class="num">{{ fmt(p.volume, 2) }}</td>
            <td class="num">{{ fmt(p.entry, 2) }}</td>
            <td class="num text-down">{{ fmt(p.sl, 2) }}</td>
            <td class="num text-up">{{ fmt(p.tp, 2) }}</td>
            <td class="num">{{ fmt(p.current_price, 2) }}</td>
            <td class="num" :class="p.points >= 0 ? 'text-up' : 'text-down'">{{ fmt(p.points, 0) }}</td>
            <td class="num" :class="p.unrealized >= 0 ? 'text-up' : 'text-down'">{{ money(p.unrealized) }}</td>
            <td><span class="chip" :class="p.breakeven_done ? 'chip-up' : ''">{{ p.breakeven_done ? 'BE' : '—' }}</span></td>
            <td class="text-right">
              <button class="btn px-2 py-1 text-[10.5px]" @click="close(p.ticket)">Close</button>
            </td>
          </tr>
          <tr v-if="!positions.length">
            <td colspan="12" class="py-6 text-center text-[11.5px] text-muted">ยังไม่มีไม้ที่เปิดอยู่</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { api } from '../lib/api'
import { fmt, money } from '../lib/format'
import { positions, toast } from '../lib/store'

async function close(ticket) {
  try {
    await api.post('/api/trading/close', { ticket })
    toast(`ปิดไม้ ${ticket} แล้ว`, 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}
async function closeAll() {
  if (!confirm('ปิดทุกไม้ที่เปิดอยู่?')) return
  try {
    const res = await api.post('/api/trading/close-all')
    toast(`ปิด ${res.closed?.length || 0} ไม้`, 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}
</script>
