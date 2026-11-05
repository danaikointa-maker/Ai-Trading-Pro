<template>
  <div class="grid grid-cols-3 gap-1.5">
    <button
      v-for="m in modes"
      :key="m.id"
      class="rounded-lg border px-2 py-2 text-left transition"
      :class="mode === m.id ? 'border-gold-500/40 bg-gold-500/10' : 'border-ink-700 bg-ink-900 hover:border-ink-600'"
      @click="change(m.id)"
    >
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-semibold" :class="mode === m.id ? 'text-gold-400' : 'text-slate-300'">{{ m.label }}</span>
        <span v-if="m.id === 'full_auto' && !allowed" class="text-[9px] text-muted">🔒</span>
      </div>
      <p class="mt-1 text-[9.5px] leading-snug text-muted">{{ m.hint }}</p>
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { api } from '../lib/api'
import { mode, state, toast } from '../lib/store'

const modes = [
  { id: 'manual', label: 'Manual + AI', hint: 'AI แนะนำ ผู้ใช้กด Buy/Sell เอง' },
  { id: 'semi_auto', label: 'Semi-Auto', hint: 'AI แจ้งสัญญาณ ผู้อนุมัติ ระบบจัดการ SL/TP' },
  { id: 'full_auto', label: 'Full Auto', hint: 'EA จัดการตามกฎที่ผ่านการทดสอบ' },
]
const allowed = computed(() => Boolean(state.config?.security?.allow_full_auto && state.config?.security?.full_auto_enabled))

async function change(id) {
  try {
    await api.post('/api/trading/mode', { mode: id })
    toast(`เปลี่ยนโหมดเป็น ${id.replace('_', ' ')}`, 'success')
  } catch (err) {
    toast(err.message, 'error')
  }
}
</script>
