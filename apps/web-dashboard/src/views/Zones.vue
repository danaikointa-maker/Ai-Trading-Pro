<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Support & Resistance · Confluence Engine</h1>
        <p class="text-[11px] text-muted">3–5 แนวรับ / 3–5 แนวต้าน พร้อมน้ำหนักหลักฐานอิสระ และสถานะ confirmed / candidate</p>
      </div>
      <div class="ml-auto flex flex-wrap gap-1.5">
        <span class="chip chip-gold">price {{ fmt(snapshot?.price, digits) }}</span>
        <span class="chip">ATR {{ fmt(snapshot?.indicators?.atr_points, 0) }} pts</span>
        <span class="chip">{{ zones.length }} zones</span>
      </div>
    </header>

    <div class="grid gap-3 lg:grid-cols-[1fr_320px]">
      <div class="space-y-3">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Resistance ladder</div><span class="panel-sub">เรียงจากใกล้ราคา</span></div>
          <div class="space-y-2 px-3 py-3">
            <article v-for="z in resistancesDesc" :key="z.id" class="rounded-lg border border-ink-700/70 bg-ink-900/50 p-3">
              <div class="flex flex-wrap items-center gap-2">
                <span class="num text-[14px] font-semibold text-slate-100">{{ fmt(z.mid, digits) }}</span>
                <span class="num text-[10.5px] text-muted">band {{ fmt(z.low, digits) }} – {{ fmt(z.high, digits) }}</span>
                <span class="chip ml-auto" :class="qChip(z)">{{ z.quality }} quality</span>
                <span class="chip" :class="z.status === 'confirmed' ? 'chip-up' : 'chip-warn'">{{ z.status }}</span>
              </div>
              <div class="mt-2 flex items-center gap-2">
                <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                  <div class="h-full bg-down/70" :style="{ width: `${Math.round(z.strength * 100)}%` }" />
                </div>
                <span class="num text-[10px] text-muted">strength {{ Math.round(z.strength * 100) }}%</span>
                <span class="num text-[10px] text-muted">{{ fmt(z.distance_points, 0) }} pts / {{ fmt(z.distance_atr, 2) }} ATR</span>
                <span class="num text-[10px] text-muted">{{ z.touches }} touches</span>
              </div>
              <div class="mt-2 flex flex-wrap gap-1">
                <span v-for="e in z.evidence" :key="e.family" class="chip" :title="e.detail">
                  {{ e.label }} <span class="text-muted">+{{ fmt(e.weight, 2) }}</span>
                </span>
              </div>
              <p class="mt-1.5 text-[10px] text-muted">{{ z.note }}</p>
            </article>
            <p v-if="!resistancesDesc.length" class="py-4 text-center text-[11px] text-muted">ไม่พบแนวต้านที่ผ่านเกณฑ์</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Support ladder</div><span class="panel-sub">เรียงจากใกล้ราคา</span></div>
          <div class="space-y-2 px-3 py-3">
            <article v-for="z in supports" :key="z.id" class="rounded-lg border border-ink-700/70 bg-ink-900/50 p-3">
              <div class="flex flex-wrap items-center gap-2">
                <span class="num text-[14px] font-semibold text-slate-100">{{ fmt(z.mid, digits) }}</span>
                <span class="num text-[10.5px] text-muted">band {{ fmt(z.low, digits) }} – {{ fmt(z.high, digits) }}</span>
                <span class="chip ml-auto" :class="qChip(z)">{{ z.quality }} quality</span>
                <span class="chip" :class="z.status === 'confirmed' ? 'chip-up' : 'chip-warn'">{{ z.status }}</span>
              </div>
              <div class="mt-2 flex items-center gap-2">
                <div class="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                  <div class="h-full bg-up/70" :style="{ width: `${Math.round(z.strength * 100)}%` }" />
                </div>
                <span class="num text-[10px] text-muted">strength {{ Math.round(z.strength * 100) }}%</span>
                <span class="num text-[10px] text-muted">{{ fmt(z.distance_points, 0) }} pts / {{ fmt(z.distance_atr, 2) }} ATR</span>
                <span class="num text-[10px] text-muted">{{ z.touches }} touches</span>
              </div>
              <div class="mt-2 flex flex-wrap gap-1">
                <span v-for="e in z.evidence" :key="e.family" class="chip" :title="e.detail">
                  {{ e.label }} <span class="text-muted">+{{ fmt(e.weight, 2) }}</span>
                </span>
              </div>
              <p class="mt-1.5 text-[10px] text-muted">{{ z.note }}</p>
            </article>
          </div>
        </section>
      </div>

      <div class="space-y-3">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Confluence rules</div></div>
          <div class="space-y-2 px-4 py-3 text-[10.5px] leading-relaxed text-slate-300">
            <p><strong class="text-gold-400">หลักฐานอิสระ ≥ {{ rules.min_independent_families }} กลุ่ม</strong> จึงจัดเป็นโซนคุณภาพสูง</p>
            <p>แต่ละ “family” นับครั้งเดียว แม้จะมีหลายระดับในโซนเดียวกัน → อินดิเคเตอร์ซ้ำกันไม่สามารถหลอกระบบได้</p>
            <p>โซน <span class="text-up">confirmed</span> ต้องเคยถูกทดสอบด้วยแท่งปิดแล้วเท่านั้น</p>
            <p>โซน <span class="text-amber-300">candidate</span> คือการคาดการณ์ ยังไม่ผ่านการทดสอบ → ใช้เป็นข้อมูลประกอบ</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Evidence families</div><span class="chip">weight</span></div>
          <div class="divide-y divide-ink-700/50 px-4 py-2">
            <div v-for="(w, f) in families" :key="f" class="flex items-center justify-between py-1.5 text-[10.5px]">
              <span class="text-slate-300">{{ label(f) }}</span>
              <div class="flex items-center gap-2">
                <div class="h-1 w-16 overflow-hidden rounded-full bg-ink-700">
                  <div class="h-full bg-gold-400" :style="{ width: `${Math.round(w * 400)}%` }" />
                </div>
                <span class="num text-muted">{{ fmt(w, 2) }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Pivots & profile</div></div>
          <dl class="grid grid-cols-2 gap-x-3 px-4 py-3 text-[10.5px]">
            <div v-for="(v, k) in snapshot?.pivots || {}" :key="k" class="kv">
              <dt>{{ k }}</dt><dd>{{ fmt(v, digits) }}</dd>
            </div>
            <div class="kv"><dt>POC</dt><dd>{{ fmt(snapshot?.indicators?.poc, digits) }}</dd></div>
            <div class="kv"><dt>VAH</dt><dd>{{ fmt(snapshot?.indicators?.vah, digits) }}</dd></div>
            <div class="kv"><dt>VAL</dt><dd>{{ fmt(snapshot?.indicators?.val, digits) }}</dd></div>
            <div class="kv"><dt>VWAP</dt><dd>{{ fmt(snapshot?.indicators?.vwap, digits) }}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { fmt } from '../lib/format'
import { state } from '../lib/store'

const snapshot = computed(() => state.live?.analysis || null)
const zones = computed(() => snapshot.value?.zones || [])
const supports = computed(() => snapshot.value?.supports || [])
const resistances = computed(() => snapshot.value?.resistances || [])
const resistancesDesc = computed(() => [...resistances.value].reverse())
const digits = computed(() => snapshot.value?.spec?.digits ?? 2)
const families = computed(() => state.config?.zone_engine?.families || {
  structure_swing: 0.2, order_block: 0.16, fair_value_gap: 0.14, pivot: 0.1, fibonacci: 0.1,
  volume_profile: 0.12, vwap: 0.06, ema: 0.06, liquidity_equal_levels: 0.06, round_number: 0.04, reaction_history: 0.12,
})
const rules = computed(() => ({
  min_independent_families: state.config?.zone_engine?.high_quality_min_families ?? 3,
}))
const qChip = (z) => (z.quality === 'high' ? 'chip-up' : z.quality === 'medium' ? 'chip-gold' : 'chip')
const label = (f) =>
  ({
    structure_swing: 'Swing structure',
    order_block: 'Order block',
    fair_value_gap: 'Fair value gap',
    pivot: 'Daily pivot',
    fibonacci: 'Fibonacci',
    volume_profile: 'Volume profile',
    vwap: 'VWAP',
    ema: 'EMA',
    liquidity_equal_levels: 'Equal highs/lows',
    round_number: 'Round number',
    reaction_history: 'Reaction history',
  }[f] || f)
</script>
