<template>
  <div class="fixed inset-0 z-40 flex justify-end bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
    <aside class="flex h-full w-full max-w-[520px] flex-col border-l border-ink-700 bg-ink-900 shadow-2xl">
      <header class="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <div>
          <div class="panel-title">AI Trade Explainer</div>
          <div class="panel-sub">ตอบจากข้อมูลจริง ณ เวลานั้น ไม่มีการเดาตัวเลข</div>
        </div>
        <button class="btn px-2 py-1" @click="$emit('close')">✕</button>
      </header>

      <div class="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        <div class="flex flex-wrap gap-1.5">
          <button v-for="q in quick" :key="q" class="chip hover:border-gold-500/40 hover:text-gold-400" @click="ask(q)">{{ q }}</button>
        </div>

        <div v-if="loading" class="rounded-lg border border-ink-700 bg-ink-850 p-3 text-[11.5px] text-muted">กำลังวิเคราะห์จาก fact sheet…</div>

        <div v-if="answer" class="space-y-2">
          <div class="rounded-lg border border-gold-500/25 bg-gold-500/5 p-3 text-[12px] leading-relaxed text-slate-200">
            {{ answer.answer }}
          </div>
          <ul class="space-y-1.5">
            <li v-for="(b, i) in answer.bullets" :key="i" class="flex gap-2 text-[11.5px] leading-relaxed text-slate-300">
              <span class="mt-1 h-1 w-1 shrink-0 rounded-full bg-gold-400"></span>{{ b }}
            </li>
          </ul>
          <section v-if="answer.officer_team" class="space-y-2 rounded-lg border border-ink-700 bg-ink-850/60 p-3">
            <div class="flex items-center justify-between gap-2">
              <div class="text-[11.5px] font-semibold text-slate-200">ทีมวิเคราะห์ · อ่านอย่างเดียว</div>
              <span class="chip">{{ answer.officer_team.mode }}</span>
            </div>
            <p class="text-[9.5px] leading-relaxed text-muted">
              ใช้ facts ชุดเดียว ไม่แสดงยอด/ตำแหน่งบัญชี และไม่มีสิทธิ์ส่งคำสั่งซื้อขาย
            </p>
            <div class="space-y-1.5">
              <article v-for="officer in answer.officer_team.officers" :key="officer.role_id" class="rounded-md border border-ink-700/80 bg-ink-900/80 p-2">
                <div class="flex items-center justify-between gap-2">
                  <div class="text-[10.5px] font-medium text-slate-200">{{ officer.title }}</div>
                  <span class="text-[9px]" :class="officer.status === 'available' ? 'text-emerald-400' : officer.status === 'stale' ? 'text-amber-400' : 'text-muted'">
                    {{ officer.status }}
                  </span>
                </div>
                <p class="mt-1 text-[10.5px] leading-relaxed text-slate-300">{{ officer.summary }}</p>
                <div v-if="officer.fact_refs?.length" class="mt-1 flex flex-wrap gap-1">
                  <span v-for="ref in officer.fact_refs" :key="ref" class="chip text-[8px]">{{ ref }}</span>
                </div>
              </article>
            </div>
          </section>
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="chip chip-gold">engine: {{ answer.model_used }}</span>
            <span v-for="c in answer.citations || []" :key="c" class="chip">{{ c }}</span>
          </div>
          <details class="rounded-lg border border-ink-700 bg-ink-850/70 px-3 py-2">
            <summary class="cursor-pointer text-[10.5px] text-muted">fact sheet ที่ส่งให้โมเดล</summary>
            <pre class="mt-2 max-h-64 overflow-auto text-[9.5px] leading-relaxed text-muted">{{ JSON.stringify(answer.facts, null, 1) }}</pre>
          </details>
        </div>
      </div>

      <footer class="border-t border-ink-700 p-3">
        <div class="flex gap-2">
          <input v-model="question" class="input" placeholder="ถาม เช่น ทำไมถึง Buy? / ทำไมไม่ Sell?" @keyup.enter="ask(question)" />
          <button class="btn btn-gold" :disabled="loading || !question" @click="ask(question)">ถาม</button>
        </div>
        <p class="mt-2 text-[9.5px] text-muted">
          LLM ใช้เฉพาะเมื่อเปิด No7 Local AI (Ollama) ไว้ ไม่อย่างนั้นระบบใช้คำอธิบายแบบ deterministic
        </p>
      </footer>
    </aside>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { api } from '../lib/api'
import { state, toast } from '../lib/store'

const props = defineProps({ symbol: { type: String, default: '' } })
defineEmits(['close'])

const question = ref('ทำไมระบบถึงตัดสินใจแบบนี้?')
const answer = ref(null)
const loading = ref(false)
const quick = [
  'ทำไมถึง Buy?',
  'ทำไมถึง Sell?',
  'ทำไมไม่เทรด?',
  'ความเสี่ยงของไม้นี้อยู่ตรงไหน?',
  'โมเดลพยากรณ์แม่นแค่ไหน?',
]

async function ask(q) {
  if (!q) return
  question.value = q
  loading.value = true
  try {
    answer.value = await api.post('/api/explain', { question: q, symbol: props.symbol || state.symbol })
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    loading.value = false
  }
}
</script>
