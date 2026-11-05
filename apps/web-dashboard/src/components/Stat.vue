<template>
  <div class="rounded-lg border border-ink-700/70 bg-ink-850/70 px-3 py-2">
    <div class="label">{{ label }}</div>
    <div class="num mt-0.5 text-[14px] font-semibold" :class="tone">{{ value }}</div>
    <div v-if="hint" class="mt-0.5 text-[9.5px] text-muted">{{ hint }}</div>
  </div>
</template>

<script setup>
defineProps({
  label: String,
  value: [String, Number],
  hint: String,
  tone: { type: String, default: 'text-slate-100' },
})
</script>
