<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2">
    <transition-group name="fade">
      <div
        v-for="t in state.toasts"
        :key="t.id"
        class="pointer-events-auto rounded-lg border px-3.5 py-2.5 text-[12px] shadow-xl backdrop-blur"
        :class="{
          'border-up/40 bg-up/10 text-up': t.type === 'success',
          'border-down/40 bg-down/10 text-down': t.type === 'error',
          'border-amber-400/40 bg-amber-400/10 text-amber-200': t.type === 'warn',
          'border-ink-600 bg-ink-800/95 text-slate-200': t.type === 'info',
        }"
      >
        {{ t.message }}
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { state } from '../lib/store'
</script>
