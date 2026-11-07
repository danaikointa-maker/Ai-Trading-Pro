<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span class="chip" :class="model?.approved ? 'chip-up' : 'chip-warn'">
      {{ model?.approved ? 'model approved' : 'baseline forecast' }}
    </span>
    <span class="chip num">{{ model?.version || 'baseline-statistical' }}</span>
    <span class="chip" :title="badgeTitle">{{ validated }} validated horizons</span>
    <span v-if="ruleChip" class="chip chip-warn" :title="badgeTitle">{{ ruleChip }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { state } from '../lib/store'

const model = computed(() => state.live?.model || null)
const validated = computed(() => {
  const h = model.value?.metrics || {}
  const ok = Object.values(h).filter((m) => m.approved).length
  return `${ok}/${Object.keys(h).length || 0}`
})
// Stored approvals are stamped with the rule that granted them; a model judged by
// an older rule shows up as unapproved with the reason in its notes.
const ruleChip = computed(() => {
  const m = model.value
  if (!m) return ''
  if (!m.approved && String(m.notes || '').includes('predates approval rule')) return 'approval expired'
  return ''
})
const badgeTitle = computed(() => {
  const m = model.value
  if (!m) return 'ยังไม่มีโมเดล'
  const parts = [m.notes, m.validation, m.approval_rule ? `approval rule v${m.approval_rule}` : '']
  return parts.filter(Boolean).join(' · ')
})
</script>
