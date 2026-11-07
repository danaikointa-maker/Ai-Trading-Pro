<template>
  <div>
    <div ref="el" class="h-[260px] w-full"></div>
    <div class="mt-2 flex flex-wrap items-center gap-3 text-[10.5px] text-muted">
      <span class="flex items-center gap-1"><i class="h-1.5 w-3 rounded bg-gold-400"></i> mean path</span>
      <span class="flex items-center gap-1"><i class="h-1.5 w-3 rounded bg-gold-400/20"></i> P10–P90 band</span>
      <span class="flex items-center gap-1"><i class="h-1.5 w-3 rounded bg-slate-500"></i> current price</span>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts from '../lib/echarts'

const props = defineProps({
  bull: { type: Object, default: null },
  base: { type: Object, default: null },
  bear: { type: Object, default: null },
  price: { type: Number, default: 0 },
  digits: { type: Number, default: 2 },
})
const el = ref(null)
let chart = null

const label = (t) => new Date(t * 1000).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

function render() {
  if (!chart || !props.base?.path?.length) return
  const basePath = props.base.path
  const times = basePath.map((p) => label(p.t))
  const p10 = basePath.map((p) => p.p10)
  const p90 = basePath.map((p) => p.p90)
  const p50 = basePath.map((p) => p.p50)
  chart.setOption({
    animationDuration: 400,
    grid: { left: 46, right: 12, top: 16, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0d1117',
      borderColor: '#1a2331',
      textStyle: { color: '#e6edf3', fontSize: 11 },
      valueFormatter: (v) => (v === null || v === undefined ? '—' : Number(v).toFixed(props.digits)),
    },
    xAxis: {
      type: 'category',
      data: times,
      axisLine: { lineStyle: { color: '#1a2331' } },
      axisLabel: { color: '#8b98a9', fontSize: 9.5, interval: Math.max(0, Math.floor(times.length / 8)) },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#8b98a9', fontSize: 9.5, formatter: (v) => Number(v).toFixed(props.digits) },
      splitLine: { lineStyle: { color: 'rgba(38,51,63,0.5)' } },
    },
    series: [
      {
        name: 'p10',
        type: 'line',
        data: p10,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        stack: 'band',
        silent: true,
      },
      {
        name: 'P10–P90',
        type: 'line',
        data: p10.map((v, i) => p90[i] - v),
        symbol: 'none',
        lineStyle: { opacity: 0 },
        stack: 'band',
        areaStyle: { color: 'rgba(245,181,65,0.16)' },
        silent: true,
      },
      {
        name: 'mean path',
        type: 'line',
        data: p50,
        symbol: 'none',
        lineStyle: { color: '#f5b541', width: 1.8 },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: 'rgba(139,152,169,0.8)', type: 'dashed', width: 1 },
          label: { color: '#8b98a9', fontSize: 9, formatter: () => 'now' },
          data: [{ yAxis: props.price }],
        },
      },
    ],
  })
}

onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  render()
  new ResizeObserver(() => chart?.resize()).observe(el.value)
})
watch(() => [props.base, props.price], render, { deep: true })
onBeforeUnmount(() => chart?.dispose())
</script>
