<template>
  <div>
    <div class="flex h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
      <div class="bg-down/80" :style="{ width: pct(pDown, 1) }" />
      <div class="bg-ink-600" :style="{ width: pct(pSide, 1) }" />
      <div class="bg-up/80" :style="{ width: pct(pUp, 1) }" />
    </div>
    <div class="mt-1 flex justify-between text-[9.5px] text-muted">
      <span>down {{ pct(pDown, 0) }}</span>
      <span>side {{ pct(pSide, 0) }}</span>
      <span>up {{ pct(pUp, 0) }}</span>
    </div>
  </div>
</template>

<script setup>
const pct = (v) => `${Math.max(0, Math.min(1, Number(v) || 0)) * 100}%`
defineProps({ pUp: Number, pDown: Number, pSide: Number })
</script>
