<template>
  <section class="panel flex h-full flex-col">
    <div class="panel-head">
      <div class="panel-title">Alerts & Audit</div>
      <span class="chip">{{ alerts.length }}</span>
    </div>
    <div class="max-h-[264px] flex-1 space-y-2 overflow-y-auto px-3 py-2.5">
      <div v-for="a in alerts" :key="a.id" class="rounded-lg border border-ink-700/60 bg-ink-900/60 px-2.5 py-2">
        <div class="flex items-center justify-between gap-2">
          <span class="text-[11px] font-medium" :class="tone(a.level)">{{ a.title }}</span>
          <span class="num text-[9.5px] text-muted">{{ clock(a.t) }}</span>
        </div>
        <p class="mt-0.5 line-clamp-2 text-[10.5px] leading-relaxed text-muted">{{ a.message }}</p>
      </div>
      <p v-if="!alerts.length" class="py-6 text-center text-[11px] text-muted">ยังไม่มีการแจ้งเตือน</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { clock } from '../lib/format'
import { state } from '../lib/store'

const alerts = computed(() => state.live?.alerts || [])
const tone = (level) =>
  level === 'critical' ? 'text-down' : level === 'warning' ? 'text-amber-300' : level === 'success' ? 'text-up' : 'text-slate-300'
</script>
