<template>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
       class="h-4 w-4 shrink-0" aria-hidden="true" focusable="false">
    <path :d="paths[name] || paths.chart" />
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, required: true } })
const paths = {
  edit: 'm14 5 5 5M4 20l5-1L21 7l-5-5L4 14v6Z',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  sidebarClose: 'M3 3h18v18H3ZM9 3v18m8-13-4 4 4 4',
  sidebarOpen: 'M3 3h18v18H3ZM9 3v18m4-13 4 4-4 4',
  close: 'm5 5 14 14M5 19 19 5',
  sliders: 'M4 7h7m4 0h5M4 17h3m4 0h9M11 4v6M7 14v6',
  chart: 'M3 3v18h18M6 14l4-5 4 3 6-8',
  layers: 'm12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5',
  link: 'm10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0 12a4 4 0 0 0 6 0l5-5a4 4 0 0 0-6-6l-1 1',
  lock: 'M6 10h12v11H6ZM8 10V6a4 4 0 0 1 8 0v4m-4 5v2',
  zoomIn: 'M21 21l-5-5M9 6v6M6 9h6M16 9a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  zoomOut: 'M21 21l-5-5M6 9h6M16 9a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  width: 'M3 6v12m18-12v12M3 12h18m-14-4-4 4 4 4m10-8 4 4-4 4',
  follow: 'M4 7h11m-4-4 4 4-4 4M20 17H9m4-4-4 4 4 4',
  shift: 'M18 3v18M3 12h11m-4-4 4 4-4 4M21 8v8',
  latest: 'm5 4 10 8L5 20V4Zm14 0v16',
  fit: 'M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5M8 12h8',
  fullscreen: 'M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5',
  collapse: 'M3 8h5V3m13 5h-5V3M8 21v-5H3m13 5v-5h5',
  scale: 'M4 4v16m-2-12 2-4 2 4m-4 8 2 4 2-4M9 12l3-7 3 7m-5-2h4m3-6v16m-2-2h4',
  height: 'M12 3v18m-4-14 4-4 4 4m-8 10 4 4 4-4M4 3h3m10 0h3M4 21h3m10 0h3',
  calendar: 'M3 5h18v16H3ZM7 3v4m10-4v4M3 10h18M7 14h3m4 0h3m-10 4h3',
  eyeOff: 'm3 3 18 18M9 9a4 4 0 0 0 6 6M6 6a17 17 0 0 0-4 6s4 7 10 7a11 11 0 0 0 5-1M10 5h2c6 0 10 7 10 7a20 20 0 0 1-3 4',
  wallet: 'M20 7H4V4h14v3M4 7v14h17V7Zm12 6h5v4h-5Z',
  pnl: 'M4 20V4m0 16h16M8 15l4-4 4 2 5-7',
  clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-5v5l3 2',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6',
  logout: 'M9 3H3v18h6m5-15 6 6-6 6m-9-6h15',
  floor: 'M3 21V7h7V3h11v18H3Zm4-10v2m0 3v2m7-11h3m-3 4h3m-3 4h3',
  database: 'M21 5c0 2-4 3-9 3S3 7 3 5s4-3 9-3 9 1 9 3Zm0 0v14c0 2-4 3-9 3s-9-1-9-3V5m0 7c0 2 4 3 9 3s9-1 9-3',
  alert: 'm12 3 10 18H2L12 3Zm0 6v5m0 3v1',
}
</script>
