<template>
  <div ref="el" class="h-[220px] w-full"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import echarts from '../lib/echarts'

const props = defineProps({ curve: { type: Array, default: () => [] }, baseline: { type: Number, default: 10000 } })
const el = ref(null)
let chart = null

function render() {
  if (!chart) return
  const rows = props.curve
  chart.setOption({
    animationDuration: 300,
    grid: { left: 56, right: 14, top: 14, bottom: 26 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0d1117',
      borderColor: '#1a2331',
      textStyle: { color: '#e6edf3', fontSize: 11 },
      valueFormatter: (v) => `$${Number(v).toFixed(2)}`,
    },
    xAxis: {
      type: 'category',
      data: rows.map((p) => new Date(p.t * 1000).toLocaleString('en-GB', { day: '2-digit', hour: '2-digit', minute: '2-digit' })),
      axisLabel: { color: '#8b98a9', fontSize: 9, interval: Math.max(0, Math.floor(rows.length / 6)) },
      axisLine: { lineStyle: { color: '#1a2331' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLabel: { color: '#8b98a9', fontSize: 9.5, formatter: (v) => Number(v).toFixed(0) },
      splitLine: { lineStyle: { color: 'rgba(38,51,63,0.5)' } },
    },
    series: [{
      type: 'line',
      data: rows.map((p) => p.equity),
      symbol: 'none',
      lineStyle: { color: '#f5b541', width: 1.8 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: 'rgba(245,181,65,0.22)' }, { offset: 1, color: 'rgba(245,181,65,0.01)' }],
        },
      },
      markLine: {
        symbol: 'none', silent: true,
        lineStyle: { color: 'rgba(139,152,169,0.5)', type: 'dashed' },
        label: { color: '#8b98a9', fontSize: 9 },
        data: [{ yAxis: props.baseline, label: { formatter: 'start' } }],
      },
    }],
  })
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  new ResizeObserver(() => chart?.resize()).observe(el.value)
})
watch(() => props.curve, render, { deep: true })
onBeforeUnmount(() => chart?.dispose())
</script>
