<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">AI Trading Journal</h1>
        <p class="text-[11px] text-muted">บันทึกทุกไม้อัตโนมัติ พร้อมบทเรียนจากข้อมูลจริง (deterministic ไม่แต่งเรื่อง)</p>
      </div>
      <button class="btn ml-auto py-1.5" @click="load">Refresh</button>
    </header>

    <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-2">
        <article v-for="e in entries" :key="e.trade.ticket" class="panel p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="chip" :class="e.trade.pnl >= 0 ? 'chip-up' : 'chip-down'">{{ e.trade.direction === 'up' ? 'BUY' : 'SELL' }}</span>
            <span class="text-[12px] font-medium text-slate-100">{{ e.headline }}</span>
            <span class="ml-auto num text-[10px] text-muted">{{ datetime(e.trade.closed_at) }}</span>
          </div>
          <div class="mt-2 grid gap-2 sm:grid-cols-2">
            <div class="rounded-lg border border-up/20 bg-up/5 px-2.5 py-2">
              <div class="label text-up/80">What worked</div>
              <ul class="mt-1 space-y-0.5">
                <li v-for="w in e.what_worked" :key="w" class="text-[10.5px] leading-relaxed text-slate-300">· {{ w }}</li>
                <li v-if="!e.what_worked.length" class="text-[10.5px] text-muted">—</li>
              </ul>
            </div>
            <div class="rounded-lg border border-down/20 bg-down/5 px-2.5 py-2">
              <div class="label text-down/80">What failed</div>
              <ul class="mt-1 space-y-0.5">
                <li v-for="w in e.what_failed" :key="w" class="text-[10.5px] leading-relaxed text-slate-300">· {{ w }}</li>
                <li v-if="!e.what_failed.length" class="text-[10.5px] text-muted">—</li>
              </ul>
            </div>
          </div>
          <p class="mt-2 text-[10.5px] leading-relaxed text-amber-200/80">บทเรียน: {{ e.lesson }}</p>
          <div class="mt-1.5 flex flex-wrap gap-1">
            <span v-for="t in e.tags" :key="t" class="chip">{{ (t || '').replaceAll('_', ' ') }}</span>
            <span class="chip">MFE {{ fmt(e.trade.journal?.max_favorable_points, 0) }} pts</span>
            <span class="chip">R {{ fmt(e.trade.r_multiple, 2) }}</span>
          </div>
        </article>
        <div v-if="!entries.length" class="panel px-4 py-10 text-center text-[11.5px] text-muted">
          ยังไม่มีบันทึก — เปิดไม้ผ่าน Terminal แล้วรอไม้ปิด ระบบจะเขียน journal ให้อัตโนมัติ
        </div>
      </div>

      <div class="space-y-3">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Ask the explainer</div></div>
          <div class="space-y-2 px-4 py-3">
            <div class="flex flex-wrap gap-1.5">
              <button v-for="q in quick" :key="q" class="chip hover:border-gold-500/40 hover:text-gold-400" @click="ask(q)">{{ q }}</button>
            </div>
            <div class="flex gap-2">
              <input v-model="question" class="input" placeholder="ถามเกี่ยวกับการตัดสินใจล่าสุด…" @keyup.enter="ask(question)" />
              <button class="btn btn-gold" :disabled="loading" @click="ask(question)">ถาม</button>
            </div>
            <div v-if="answer" class="rounded-lg border border-ink-700 bg-ink-900/60 p-3">
              <p class="text-[11.5px] leading-relaxed text-slate-200">{{ answer.answer }}</p>
              <ul class="mt-2 space-y-1">
                <li v-for="(b, i) in answer.bullets" :key="i" class="flex gap-2 text-[10.5px] leading-relaxed text-muted">
                  <span class="mt-1 h-1 w-1 shrink-0 rounded-full bg-gold-400"></span>{{ b }}
                </li>
              </ul>
              <div class="mt-2 flex flex-wrap gap-1">
                <span class="chip chip-gold">{{ answer.model_used }}</span>
                <span v-for="c in answer.citations" :key="c" class="chip">{{ c }}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Journal stats</div></div>
          <dl class="px-4 py-3">
            <div class="kv"><dt>Entries</dt><dd>{{ entries.length }}</dd></div>
            <div class="kv"><dt>Wins / losses</dt><dd>{{ wins }} / {{ losses }}</dd></div>
            <div class="kv"><dt>Total P&L</dt><dd :class="total >= 0 ? 'text-up' : 'text-down'">{{ money(total) }}</dd></div>
          </dl>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { datetime, fmt, money } from '../lib/format'
import { state, toast } from '../lib/store'

const entries = ref([])
const question = ref('ทำไมระบบถึงตัดสินใจแบบนี้?')
const answer = ref(null)
const loading = ref(false)
const quick = ['ทำไมไม่เทรด?', 'ทำไมถึง Buy?', 'โมเดลแม่นแค่ไหน?', 'ความเสี่ยงอยู่ตรงไหน?']

const wins = computed(() => entries.value.filter((e) => (e.trade?.pnl || 0) > 0).length)
const losses = computed(() => entries.value.filter((e) => (e.trade?.pnl || 0) <= 0).length)
const total = computed(() => entries.value.reduce((a, e) => a + (e.trade?.pnl || 0), 0))

async function load() {
  try {
    const data = await api.get('/api/trading/journal?limit=40')
    entries.value = data.entries || []
  } catch (err) {
    toast(err.message, 'error')
  }
}
async function ask(q) {
  if (!q) return
  loading.value = true
  try {
    answer.value = await api.post('/api/explain', { question: q, symbol: state.symbol })
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
