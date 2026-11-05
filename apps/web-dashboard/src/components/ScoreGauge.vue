<template>
  <div class="relative grid place-items-center" :style="{ width: size + 'px', height: size + 'px' }">
    <svg :width="size" :height="size" class="rotate-[-90deg]">
      <circle :cx="size / 2" :cy="size / 2" :r="r" fill="none" stroke="#1a2331" :stroke-width="stroke" />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="r"
        fill="none"
        :stroke="color"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        class="transition-all duration-500"
      />
    </svg>
    <div class="absolute text-center leading-none">
      <div class="num font-semibold" :style="{ fontSize: size * 0.26 + 'px', color }">{{ Math.round(score) }}</div>
      <div class="text-[9px] uppercase tracking-[0.16em] text-muted">{{ label }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Number, default: 0 },
  size: { type: Number, default: 92 },
  label: { type: String, default: 'score' },
  stroke: { type: Number, default: 7 },
})
const r = computed(() => props.size / 2 - props.stroke)
const circumference = computed(() => 2 * Math.PI * r.value)
const offset = computed(() => circumference.value * (1 - Math.min(100, Math.max(0, props.score)) / 100))
const color = computed(() => (props.score >= 85 ? '#34d399' : props.score >= 70 ? '#f5b541' : props.score >= 50 ? '#fbbf24' : '#8b98a9'))
</script>
