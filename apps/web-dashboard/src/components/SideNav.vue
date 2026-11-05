<template>
  <aside class="sticky top-0 h-screen w-[212px] shrink-0 flex-col border-r border-ink-700/70 bg-ink-900/80 px-3 py-4 backdrop-blur">
    <div class="mb-5 flex items-center gap-2.5 px-1">
      <div class="grid h-9 w-9 place-items-center rounded-lg bg-gold-500/15 text-[15px] font-black text-gold-400 ring-1 ring-gold-500/30">N7</div>
      <div class="leading-tight">
        <div class="text-[12.5px] font-semibold tracking-wide text-slate-100">NO7 AI TRADING</div>
        <div class="text-[10px] uppercase tracking-[0.18em] text-muted">Pro · V1</div>
      </div>
    </div>

    <nav class="flex flex-1 flex-col gap-1">
      <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="nav-link" active-class="active">
        <component :is="'span'" v-html="item.icon" class="grid h-4 w-4 place-items-center opacity-80" />
        <span class="flex-1">{{ item.label }}</span>
        <span v-if="item.badge" class="chip px-1.5 py-0 text-[9.5px]">{{ item.badge }}</span>
      </RouterLink>
    </nav>

    <div class="mt-4 rounded-lg border border-ink-700/70 bg-ink-850/80 p-3">
      <div class="label mb-1.5">Connection</div>
      <div class="flex items-center gap-2 text-[11.5px]">
        <span class="h-1.5 w-1.5 rounded-full" :class="state.connected ? 'bg-up' : 'bg-amber-400'" />
        <span class="text-slate-300">{{ state.connected ? 'Live stream' : 'Reconnecting' }}</span>
      </div>
      <div class="mt-2 flex items-center justify-between text-[10.5px] text-muted">
        <span>transport</span><span class="num">{{ state.transport }}</span>
      </div>
      <div class="mt-1 flex items-center justify-between text-[10.5px] text-muted">
        <span>feed</span><span class="num">{{ state.live?.feed || '—' }}</span>
      </div>
    </div>
    <div class="mt-3 rounded-lg border border-amber-400/20 bg-amber-400/5 p-3 text-[10.5px] leading-relaxed text-amber-200/80">
      Demo / paper account. ตรวจสอบสถานะทางกฎหมายของโบรกเกอร์ก่อนใช้เงินจริง
    </div>
  </aside>
</template>

<script setup>
import { state } from '../lib/store'
import { nav } from '../lib/nav'
</script>
