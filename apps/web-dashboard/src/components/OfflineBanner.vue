<template>
  <!-- A trading screen must never look live while it is not. -->
  <div
    v-if="offline"
    class="sticky top-0 z-40 bg-amber-500/15 px-3 py-1.5 text-center text-[11px] font-medium text-amber-200 backdrop-blur"
  >
    ไม่มีการเชื่อมต่อ — ตัวเลขบนจอเป็นข้อมูลครั้งล่าสุด ไม่ใช่ราคาปัจจุบัน
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { state } from '../lib/store'

const online = ref(navigator.onLine)
// Do not flash "offline" during the first second while the socket is still
// opening: only warn once the app *was* connected and then lost the stream.
const wasConnected = ref(false)
watch(() => state.connected, (value) => { if (value) wasConnected.value = true })

const sync = () => { online.value = navigator.onLine }
onMounted(() => {
  window.addEventListener('online', sync)
  window.addEventListener('offline', sync)
})
onUnmounted(() => {
  window.removeEventListener('online', sync)
  window.removeEventListener('offline', sync)
})

// The socket can also drop while the browser still believes it is online.
const offline = computed(() => !online.value || (wasConnected.value && state.symbol && !state.connected))
</script>
