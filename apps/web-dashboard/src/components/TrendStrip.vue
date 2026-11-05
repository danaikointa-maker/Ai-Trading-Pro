<template>
  <div class="grid grid-cols-5 gap-1.5">
    <div
      v-for="t in trends"
      :key="t.timeframe"
      class="rounded-lg border border-ink-700/70 bg-ink-900/60 px-2 py-1.5"
    >
      <div class="flex items-center justify-between">
        <span class="text-[10px] font-medium text-muted">{{ t.timeframe }}</span>
        <span class="text-[11px]" :class="tone(t.direction)">{{ arrow(t.direction) }}</span>
      </div>
      <div class="mt-0.5 text-[10px]" :class="tone(t.direction)">{{ t.direction }}</div>
      <div class="mt-1 h-1 overflow-hidden rounded-full bg-ink-700">
        <div class="h-full rounded-full" :class="t.direction === 'up' ? 'bg-up' : t.direction === 'down' ? 'bg-down' : 'bg-ink-600'"
             :style="{ width: `${Math.round((t.strength || 0) * 100)}%` }" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { state } from '../lib/store'

const trends = computed(() => state.live?.analysis?.trend || [])
const tone = (d) => (d === 'up' ? 'text-up' : d === 'down' ? 'text-down' : 'text-muted')
const arrow = (d) => (d === 'up' ? '▲' : d === 'down' ? '▼' : '→')
</script>
