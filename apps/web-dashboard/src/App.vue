<template>
  <div class="min-h-full text-slate-200">
    <div v-if="isAuthed" class="flex min-h-screen">
      <SideNav class="hidden lg:flex" />
      <div class="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <TopBar />
        <main class="mx-auto w-full max-w-[1700px] flex-1 px-3 py-3 pb-24 sm:px-4 lg:pb-16">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </main>
        <footer class="border-t border-ink-700/60 px-4 py-3 text-[10.5px] leading-relaxed text-muted">
          <div class="mx-auto flex max-w-[1700px] flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <span>
              No7 AI Trading Pro V1 · ระบบเพื่อการศึกษา/ทดลอง — ไม่ใช่คำแนะนำการลงทุน
              ผลการทดสอบย้อนหลังไม่รับประกันผลลัพธ์ในอนาคต
            </span>
            <span class="num flex items-center gap-3">
              <span>API <a class="text-gold-400/80 hover:text-gold-400" href="/api/docs" target="_blank">docs</a></span>
              <span>v1.0.0</span>
            </span>
          </div>
        </footer>
      </div>
    </div>
    <router-view v-else />
    <MobileNav v-if="isAuthed" />
    <Toasts />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import SideNav from './components/SideNav.vue'
import MobileNav from './components/MobileNav.vue'
import OfflineBanner from './components/OfflineBanner.vue'
import TopBar from './components/TopBar.vue'
import Toasts from './components/Toasts.vue'
import { bootstrap, startLive, state, stopLive } from './lib/store'
import { getToken } from './lib/api'

const isAuthed = computed(() => Boolean(state.token || getToken()))

let booted = false
onMounted(async () => {
  if (isAuthed.value) {
    booted = true
    await bootstrap().catch(() => {})
    startLive()
  }
})
onUnmounted(() => stopLive())
</script>
