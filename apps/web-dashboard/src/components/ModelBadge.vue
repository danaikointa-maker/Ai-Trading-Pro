<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span class="chip" :class="model?.approved ? 'chip-up' : 'chip-warn'">
      {{ model?.approved ? 'model approved' : 'baseline forecast' }}
    </span>
    <span class="chip num">{{ model?.version || 'baseline-statistical' }}</span>
    <span class="chip" :title="model?.notes">{{ validated }} validated horizons</span>
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
</script>
