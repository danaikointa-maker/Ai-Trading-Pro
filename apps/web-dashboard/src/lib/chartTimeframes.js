import { computed, ref, watch } from 'vue'

export const CHART_TIMEFRAMES = [
  { id: 'M1', seconds: 60 }, { id: 'M3', seconds: 180 },
  { id: 'M5', seconds: 300 }, { id: 'M15', seconds: 900 },
  { id: 'M30', seconds: 1800 }, { id: 'H1', seconds: 3600 },
  { id: 'H4', seconds: 14400 }, { id: 'D1', seconds: 86400 },
]
export const DEFAULT_TIMEFRAMES = ['M1', 'M3', 'M5', 'M15', 'H1', 'H4']
const KEY = 'no7.chart.timeframes.v1'
export function normalizeTimeframes(value) {
  if (!Array.isArray(value)) return [...DEFAULT_TIMEFRAMES]
  const valid = CHART_TIMEFRAMES.map(tf => tf.id).filter(id => value.includes(id))
  return valid.length ? valid : [...DEFAULT_TIMEFRAMES]
}
let saved
try { saved = JSON.parse(localStorage.getItem(KEY) || 'null') } catch { /* default preferences */ }
export const pinnedTimeframes = ref(normalizeTimeframes(saved))
export const visibleTimeframes = computed(() => CHART_TIMEFRAMES.filter(tf => pinnedTimeframes.value.includes(tf.id)))
watch(pinnedTimeframes, value => {
  try { localStorage.setItem(KEY, JSON.stringify(value)) } catch { /* storage may be disabled */ }
}, { deep: true })
export function toggleTimeframe(id) {
  if (!CHART_TIMEFRAMES.some(tf => tf.id === id)) return
  if (pinnedTimeframes.value.includes(id)) {
    if (pinnedTimeframes.value.length > 1) pinnedTimeframes.value = pinnedTimeframes.value.filter(tf => tf !== id)
  } else pinnedTimeframes.value = normalizeTimeframes([...pinnedTimeframes.value, id])
}
export function resetTimeframes() { pinnedTimeframes.value = [...DEFAULT_TIMEFRAMES] }
export function timeframeSeconds(id) { return CHART_TIMEFRAMES.find(tf => tf.id === id)?.seconds }
