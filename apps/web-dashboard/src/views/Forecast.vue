<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-center gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">AI Price Forecast</h1>
        <p class="text-[11px] text-muted">แสดง 3 สถานการณ์และช่วง P10–P90 ไม่ใช่เส้นเดียวที่บอกอนาคต</p>
      </div>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <ModelBadge />
        <button class="btn py-1.5" :disabled="training" @click="train">
          {{ training ? `training ${trainingPct}%` : 'Train / re-validate' }}
        </button>
      </div>
    </header>

    <div v-if="!bundle" class="panel px-4 py-8 text-center text-[12px] text-muted">กำลังโหลด forecast…</div>

    <template v-else>
      <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section class="panel">
          <div class="panel-head">
            <div>
              <div class="panel-title">{{ bundle.symbol }} · scenarios</div>
              <div class="panel-sub">
                {{ bundle.method }} · model {{ bundle.model_version }} ·
                {{ bundle.model_approved ? 'validated horizons available' : 'UNVALIDATED (baseline)' }}
              </div>
            </div>
            <span class="chip" :class="bundle.model_approved ? 'chip-up' : 'chip-warn'">confidence {{ pct(bundle.confidence, 0) }}</span>
          </div>
          <div class="px-3 py-3">
            <ForecastFan :bull="scenario('bull')" :base="scenario('base')" :bear="scenario('bear')"
                         :price="bundle.price" :digits="digits" />
          </div>
          <div class="grid grid-cols-3 gap-2 border-t border-ink-700/60 px-3 py-3">
            <div v-for="s in bundle.scenarios" :key="s.name" class="rounded-lg border border-ink-700/70 bg-ink-900/60 px-2.5 py-2">
              <div class="flex items-center justify-between">
                <span class="text-[10px] uppercase tracking-wide" :class="s.name === 'bull' ? 'text-up' : s.name === 'bear' ? 'text-down' : 'text-slate-200'">{{ s.name }}</span>
                <span class="num text-[10px] text-muted">{{ pct(s.probability, 0) }}</span>
              </div>
              <div class="num mt-1 text-[13px] font-semibold text-slate-100">{{ fmt(s.target_price, digits) }}</div>
              <p class="mt-0.5 text-[9.5px] leading-snug text-muted">{{ s.description }}</p>
            </div>
          </div>
        </section>

        <div class="space-y-3">
          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">Horizon detail</div>
              <div class="flex gap-1">
                <button v-for="h in bundle.horizons" :key="h.horizon_minutes"
                        class="rounded-md px-1.5 py-1 text-[10px] font-medium"
                        :class="selected === h.horizon_minutes ? 'bg-gold-500/15 text-gold-400' : 'text-muted hover:text-slate-200'"
                        @click="selected = h.horizon_minutes">
                  {{ h.horizon_minutes }}m
                </button>
              </div>
            </div>
            <div class="px-4 py-3">
              <ProbBars :p-up="active.p_up" :p-down="active.p_down" :p-side="active.p_sideways" />
              <dl class="mt-3 space-y-0">
                <div class="kv"><dt>Expected range P10–P90</dt>
                  <dd>{{ fmt(active.p10_price, digits) }} – {{ fmt(active.p90_price, digits) }}</dd></div>
                <div class="kv"><dt>In points</dt>
                  <dd>{{ fmt(active.p10_points, 0) }} … {{ fmt(active.p90_points, 0) }}</dd></div>
                <div class="kv"><dt>Median path</dt><dd>{{ fmt(active.p50_price, digits) }} ({{ fmt(active.p50_points, 0) }} pts)</dd></div>
                <div class="kv"><dt>P(TP before SL)</dt>
                  <dd :class="active.p_tp_before_sl > 0.45 ? 'text-up' : 'text-amber-300'">
                    {{ pct(active.p_tp_before_sl, 0) }}
                    <span class="text-[10px] text-muted">(ref {{ fmt(active.tp_points, 0) }}/{{ fmt(active.sl_points, 0) }} pts)</span>
                  </dd></div>
                <div class="kv"><dt>Expected volatility</dt><dd>{{ fmt(active.volatility_points, 0) }} pts</dd></div>
                <div class="kv"><dt>Confidence</dt><dd>{{ pct(active.confidence, 0) }}</dd></div>
                <div class="kv"><dt>Calibrated</dt>
                  <dd><span class="chip" :class="active.calibrated ? 'chip-up' : 'chip-warn'">{{ active.calibrated ? 'yes (isotonic)' : 'no' }}</span></dd></div>
                <div class="kv"><dt>OOS directional accuracy</dt>
                  <dd>{{ active.directional_accuracy_oos ? pct(active.directional_accuracy_oos, 1) : '—' }}</dd></div>
              </dl>
              <p class="mt-2 rounded-lg border border-ink-700/60 bg-ink-900/60 px-2.5 py-2 text-[10px] leading-relaxed text-muted">
                {{ active.coverage_note }}
              </p>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><div class="panel-title">Invalidation</div><span class="chip chip-warn">watch</span></div>
            <ul class="space-y-2 px-4 py-3">
              <li v-for="line in bundle.invalidation" :key="line" class="flex gap-2 text-[10.5px] leading-relaxed text-slate-300">
                <span class="mt-1 h-1 w-1 shrink-0 rounded-full bg-amber-400"></span>{{ line }}
              </li>
            </ul>
          </section>
        </div>
      </div>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">All horizons</div>
          <div class="panel-sub"> probabilities คือความน่าจะเป็น ไม่ใช่คะแนนความแม่นยำ </div>
        </div>
        <div class="overflow-x-auto">
          <table class="table-base">
            <thead>
              <tr>
                <th>Horizon</th><th>Up</th><th>Down</th><th>Sideways</th><th>P10</th><th>P50</th><th>P90</th>
                <th>P(TP→SL)</th><th>Vol</th><th>Conf.</th><th>Model</th><th>OOS acc.</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in bundle.horizons" :key="h.horizon_minutes" class="cursor-pointer hover:bg-ink-800/50"
                  :class="selected === h.horizon_minutes ? 'bg-ink-800/40' : ''" @click="selected = h.horizon_minutes">
                <td class="num font-medium text-slate-200">{{ h.horizon_minutes }}m</td>
                <td class="num text-up">{{ pct(h.p_up, 1) }}</td>
                <td class="num text-down">{{ pct(h.p_down, 1) }}</td>
                <td class="num text-muted">{{ pct(h.p_sideways, 1) }}</td>
                <td class="num">{{ fmt(h.p10_price, digits) }}</td>
                <td class="num">{{ fmt(h.p50_price, digits) }}</td>
                <td class="num">{{ fmt(h.p90_price, digits) }}</td>
                <td class="num">{{ pct(h.p_tp_before_sl, 0) }}</td>
                <td class="num">{{ fmt(h.volatility_points, 0) }}</td>
                <td class="num">{{ pct(h.confidence, 0) }}</td>
                <td><span class="chip" :class="h.calibrated ? 'chip-up' : ''">{{ h.calibrated ? 'calibrated' : 'baseline' }}</span></td>
                <td class="num">{{ h.directional_accuracy_oos ? pct(h.directional_accuracy_oos, 1) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="grid gap-3 lg:grid-cols-2">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Out-of-sample evaluation</div>
            <span class="chip">time-ordered split · {{ foldsLabel }}</span>
          </div>
          <div class="overflow-x-auto">
            <table class="table-base">
              <thead><tr><th>H</th><th>Directional acc.</th><th>Brier</th><th>Baseline Brier</th><th>Δ</th><th>P10–P90 cover</th><th title="chronological folds that clear the same gates">Folds</th><th>Gate</th></tr></thead>
              <tbody>
                <tr v-for="(m, key) in metrics" :key="key">
                  <td class="num">{{ key }}m</td>
                  <td class="num">{{ pct(m.directional_accuracy, 1) }}</td>
                  <td class="num">{{ fmt(m.brier, 3) }}</td>
                  <td class="num text-muted">{{ fmt(m.baseline_brier, 3) }}</td>
                  <td class="num" :class="m.brier_improvement > 0 ? 'text-up' : 'text-down'">{{ signed(m.brier_improvement, 4) }}</td>
                  <td class="num">{{ pct(m.coverage_p10_p90, 0) }}</td>
                  <td class="num" :title="foldsTitle(m)" :class="foldsClass(m)">{{ foldsText(m) }}</td>
                  <td><span class="chip" :class="m.approved ? 'chip-up' : 'chip-warn'">{{ m.approved ? 'pass' : 'fail' }}</span></td>
                </tr>
                <tr v-if="!Object.keys(metrics).length"><td colspan="8" class="py-4 text-center text-[11px] text-muted">ยังไม่มีโมเดลที่ฝึกเสร็จ</td></tr>
              </tbody>
            </table>
          </div>
          <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
            เกณฑ์ผ่าน: directional accuracy ≥ {{ pct(thresholds.dir, 0) }} และ Brier ดีกว่าค่าฐาน ≥ {{ fmt(thresholds.brier, 2) }}.
            ช่วงที่โมเดลไม่ผ่านเกณฑ์ ระบบจะใช้ค่าฐานสถิติและระบุว่า “ยังไม่ผ่านการสอบเทียบ”.
          </p>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Model narrative</div><span class="chip chip-gold">{{ bundle.model_version }}</span></div>
          <div class="px-4 py-3">
            <p class="text-[11.5px] leading-relaxed text-slate-300">{{ bundle.narrative }}</p>
            <div class="divider"></div>
            <p class="text-[10.5px] leading-relaxed text-muted">
              ระบบไม่ถือว่า Signal Score 90 = โอกาสชนะ 90% คะแนนสัญญาณเป็น heuristic ส่วนความน่าจะเป็นผ่านการสอบเทียบแยกต่างหาก
              (isotonic regression บนช่วง calibration ที่ไม่ถูกใช้ฝึก)
            </p>
            <button class="btn mt-3 w-full py-1.5" @click="train">Train ใหม่ + เทียบ baseline</button>
            <p v-if="trainingMsg" class="mt-2 text-[10px] text-muted">{{ trainingMsg }}</p>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import ForecastFan from '../components/ForecastFan.vue'
import ModelBadge from '../components/ModelBadge.vue'
import ProbBars from '../components/ProbBars.vue'
import { api } from '../lib/api'
import { fmt, pct, signed } from '../lib/format'
import { state, toast } from '../lib/store'

const bundle = computed(() => state.live?.forecast || null)
const digits = computed(() => bundle.value?.horizons?.[0] ? (state.live?.analysis?.spec?.digits ?? 2) : 2)
const metrics = computed(() => state.live?.model?.metrics || {})
const training = computed(() => ['running', 'started'].includes(state.live?.training?.state))
const trainingPct = computed(() => Math.round(state.live?.training?.pct || 0))
const trainingMsg = computed(() => state.live?.training?.message || '')
const thresholds = { dir: 0.52, brier: 0.02 }

// Fold consistency: a single lucky slice used to decide approval, so the flag
// flipped between runs. Show how many chronological folds cleared the bar.
function foldPassed(m) {
  const rate = m?.fold_pass_rate
  const used = m?.folds_used ?? 0
  if (rate === undefined || !used) return null
  return { passed: Math.round(rate * used), used }
}

function foldsText(m) {
  const f = foldPassed(m)
  return f ? `${f.passed}/${f.used}` : '—'
}

function foldsClass(m) {
  const f = foldPassed(m)
  if (!f) return 'text-muted'
  return f.passed / f.used >= 0.75 ? 'text-up' : 'text-down'
}

function foldsTitle(m) {
  if (m?.fold_directional_median === undefined) return 'ยังไม่มีข้อมูล fold'
  return `median directional ${pct(m.fold_directional_median, 1)} · `
    + `median Brier Δ ${signed(m.fold_brier_improvement_median, 4)} · `
    + `แย่สุด ${signed(m.fold_brier_improvement_min, 4)}`
}

const foldsLabel = computed(() => {
  const first = Object.values(metrics.value)[0]
  const f = foldPassed(first)
  return f ? `${f.used} folds · ต้องผ่าน ≥75%` : 'fold check'
})
const selected = ref(60)

watch(bundle, (b) => {
  if (b && !b.horizons.find((h) => h.horizon_minutes === selected.value)) {
    selected.value = b.horizons[0]?.horizon_minutes || 5
  }
}, { immediate: true })

const active = computed(() => {
  const hs = bundle.value?.horizons || []
  return hs.find((h) => h.horizon_minutes === selected.value) || hs[0] || {
    p_up: 0, p_down: 0, p_sideways: 1, p10_price: 0, p90_price: 0, p10_points: 0, p90_points: 0,
    p50_price: 0, p50_points: 0, p_tp_before_sl: 0, tp_points: 0, sl_points: 0, volatility_points: 0,
    confidence: 0, calibrated: false, coverage_note: '', directional_accuracy_oos: null,
  }
})
const scenario = (name) => (bundle.value?.scenarios || []).find((s) => s.name === name) || null

async function train() {
  try {
    await api.post('/api/forecast/train', { symbol: state.symbol, force: true })
    toast('เริ่มฝึกโมเดลใหม่ (background)', 'info')
  } catch (err) {
    toast(err.message, 'error')
  }
}
</script>
