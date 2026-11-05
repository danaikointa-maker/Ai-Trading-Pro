<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <div class="panel-title">Support & Resistance</div>
        <div class="panel-sub">{{ supports.length }} แนวรับ · {{ resistances.length }} แนวต้าน (ขั้นต่ำ 3 ระดับ)</div>
      </div>
      <RouterLink to="/zones" class="chip hover:text-slate-200">รายละเอียด →</RouterLink>
    </div>
    <div class="grid gap-3 px-3 py-3 sm:grid-cols-2">
      <div>
        <div class="label mb-1.5 text-down/80">Resistance</div>
        <div v-for="z in resistances.slice(0, 4)" :key="z.id" class="mb-1.5 rounded-lg border border-ink-700/60 bg-ink-900/50 px-2.5 py-1.5">
          <div class="flex items-center justify-between">
            <span class="num text-[12px] text-slate-200">{{ fmt(z.mid, digits) }}</span>
            <span class="chip" :class="qualityChip(z)">{{ z.quality }} · {{ z.status }}</span>
          </div>
          <div class="mt-1 flex items-center gap-2">
            <div class="h-1 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div class="h-full bg-down/70" :style="{ width: `${Math.round(z.strength * 100)}%` }" />
            </div>
            <span class="num text-[9.5px] text-muted">{{ Math.round(z.strength * 100) }}%</span>
            <span class="num text-[9.5px] text-muted">{{ fmt(z.distance_points, 0) }}p</span>
          </div>
          <div class="mt-1 flex flex-wrap gap-1">
            <span v-for="f in z.families.slice(0, 4)" :key="f" class="rounded bg-ink-800 px-1 py-0.5 text-[9px] text-muted">
              {{ shortFam(f) }}
            </span>
          </div>
        </div>
      </div>
      <div>
        <div class="label mb-1.5 text-up/80">Support</div>
        <div v-for="z in supports.slice(0, 4)" :key="z.id" class="mb-1.5 rounded-lg border border-ink-700/60 bg-ink-900/50 px-2.5 py-1.5">
          <div class="flex items-center justify-between">
            <span class="num text-[12px] text-slate-200">{{ fmt(z.mid, digits) }}</span>
            <span class="chip" :class="qualityChip(z)">{{ z.quality }} · {{ z.status }}</span>
          </div>
          <div class="mt-1 flex items-center gap-2">
            <div class="h-1 flex-1 overflow-hidden rounded-full bg-ink-700">
              <div class="h-full bg-up/70" :style="{ width: `${Math.round(z.strength * 100)}%` }" />
            </div>
            <span class="num text-[9.5px] text-muted">{{ Math.round(z.strength * 100) }}%</span>
            <span class="num text-[9.5px] text-muted">{{ fmt(z.distance_points, 0) }}p</span>
          </div>
          <div class="mt-1 flex flex-wrap gap-1">
            <span v-for="f in z.families.slice(0, 4)" :key="f" class="rounded bg-ink-800 px-1 py-0.5 text-[9px] text-muted">
              {{ shortFam(f) }}
            </span>
          </div>
        </div>
      </div>
    </div>
    <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
      โซน “confirmed” ผ่านการทดสอบซ้ำด้วยแท่งปิดแล้ว ส่วน “candidate” เป็นเพียงการคาดการณ์ —
      ระบบจึงไม่เกิดปัญหา repainting
    </p>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { fmt } from '../lib/format'
import { state } from '../lib/store'

const supports = computed(() => state.live?.analysis?.supports || [])
const resistances = computed(() => state.live?.analysis?.resistances || [])
const digits = computed(() => state.live?.analysis?.spec?.digits ?? 2)
const qualityChip = (z) => (z.quality === 'high' ? 'chip-up' : z.quality === 'medium' ? 'chip-gold' : 'chip')
const shortFam = (f) =>
  ({
    structure_swing: 'swing',
    order_block: 'OB',
    fair_value_gap: 'FVG',
    volume_profile: 'VP',
    liquidity_equal_levels: 'liquidity',
    reaction_history: 'reaction',
    fibonacci: 'fib',
    pivot: 'pivot',
    round_number: 'round',
    vwap: 'VWAP',
    ema: 'EMA',
  }[f] || f)
</script>
