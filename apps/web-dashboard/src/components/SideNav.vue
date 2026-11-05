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

const icon = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4">${path}</svg>`

const nav = [
  { to: '/', label: 'Terminal', badge: 'live', icon: icon('<path d="M3 17l5-6 4 3 5-7 4 4"/><path d="M3 21h18"/>') },
  { to: '/forecast', label: 'AI Forecast', icon: icon('<path d="M4 19V5"/><path d="M4 15c3 0 4-8 8-8s5 6 8 6"/><path d="M16 19h4"/>') },
  { to: '/zones', label: 'Zones S/R', icon: icon('<path d="M4 7h16M4 12h16M4 17h16"/>') },
  { to: '/trades', label: 'Trades', icon: icon('<path d="M4 6h16v12H4z"/><path d="M8 10h8M8 14h5"/>') },
  { to: '/risk', label: 'Risk Engine', icon: icon('<path d="M12 3l8 4v6c0 5-4 7-8 8-4-1-8-3-8-8V7z"/><path d="M9 12l2 2 4-4"/>') },
  { to: '/backtest', label: 'Backtest Lab', icon: icon('<path d="M4 20V8m5 12V4m5 16v-7m5 7V9"/>') },
  { to: '/journal', label: 'AI Journal', icon: icon('<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>') },
  { to: '/brokers', label: 'Brokers', icon: icon('<path d="M3 10h18M5 10V6l7-3 7 3v4"/><path d="M5 10v9h14v-9"/>') },
  { to: '/system', label: 'System', icon: icon('<circle cx="12" cy="12" r="3"/><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6l2.1 2.1m0-12.8l-2.1 2.1M7.7 16.3l-2.1 2.1"/>') },
]
</script>
