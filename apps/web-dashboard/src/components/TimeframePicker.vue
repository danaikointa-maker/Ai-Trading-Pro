<template>
  <div class="flex flex-wrap items-center gap-1" aria-label="เลือกกรอบเวลา">
    <button v-for="tf in visibleTimeframes" :key="tf.id" type="button" class="btn px-2 py-1 text-[11px]"
            :class="state.timeframe === tf.id ? 'text-gold' : ''" :aria-pressed="state.timeframe === tf.id"
            @click="setTimeframe(tf.id)">{{ tf.id }}</button>
    <span v-if="!pinnedTimeframes.includes(state.timeframe)" class="chip">กำลังดู {{ state.timeframe }}</span>
    <details class="relative">
      <summary class="btn cursor-pointer list-none px-2 py-1 text-[11px]">Timeframe เพิ่มเติม / จัดปุ่ม ▾</summary>
      <div class="absolute left-0 top-full z-50 mt-1 w-64 rounded-lg border border-ink-700 bg-ink-900 p-3 shadow-xl">
        <p class="mb-2 text-[11px] text-muted">เลือกดู หรือ ✓ เพื่อแสดงเป็นปุ่มประจำ</p>
        <div v-for="tf in CHART_TIMEFRAMES" :key="tf.id" class="flex items-center justify-between gap-3 py-1">
          <button type="button" class="btn w-14 py-1 text-[11px]" :aria-pressed="state.timeframe === tf.id" @click="setTimeframe(tf.id)">{{ tf.id }}</button>
          <label class="flex items-center gap-2 text-[11px]">
            <input type="checkbox" :checked="pinnedTimeframes.includes(tf.id)"
                   :disabled="pinnedTimeframes.length === 1 && pinnedTimeframes.includes(tf.id)"
                   :aria-label="`แสดงปุ่ม ${tf.id}`" @change="toggleTimeframe(tf.id)" /> แสดงปุ่ม
          </label>
        </div>
        <button type="button" class="btn mt-2 w-full py-1 text-[11px]" @click="resetTimeframes">คืนปุ่มเริ่มต้น</button>
        <p class="mt-2 text-[10px] text-muted">จำไว้ในเบราว์เซอร์นี้ · ต้องเหลืออย่างน้อย 1 ปุ่ม</p>
      </div>
    </details>
  </div>
</template>

<script setup>
import { setTimeframe, state } from '../lib/store'
import { CHART_TIMEFRAMES, pinnedTimeframes, resetTimeframes, toggleTimeframe, visibleTimeframes } from '../lib/chartTimeframes'
</script>
