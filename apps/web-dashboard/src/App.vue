<template>
  <div class="min-h-full text-slate-200">
    <!-- `showApp` also requires a non-login route: a valid token while the router
         is still on /login used to render the login form inside the app shell,
         which reads as "logged in but stuck on the login page". -->
    <div v-if="showApp" class="flex min-h-screen">
      <SideNav class="hidden lg:flex" />
      <div class="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main class="mx-auto w-full max-w-[1700px] flex-1 px-3 py-3 pb-16 sm:px-4">
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

    <!-- Brief hand-off screen between "token stored" and "route changed". -->
    <div v-else-if="isAuthed" class="grid min-h-screen place-items-center px-6 text-center">
      <div>
        <div class="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-ink-700 border-t-gold-400"></div>
        <div class="text-[13px] font-semibold text-slate-200">กำลังเข้าสู่หน้าจอเทรด…</div>
        <div class="mt-1 text-[11px] text-muted">โหลดแดชบอร์ดและเริ่มสตรีมราคา</div>
        <button class="mt-4 text-[11px] text-gold-400/90 underline decoration-dotted" @click="goHome">
          ไปที่หน้าเทอร์มินัล
        </button>
      </div>
    </div>

    <router-view v-else />
    <Toasts />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SideNav from './components/SideNav.vue'
import TopBar from './components/TopBar.vue'
import Toasts from './components/Toasts.vue'
import { bootstrap, startLive, state, stopLive } from './lib/store'
import { getToken } from './lib/api'

const route = useRoute()
const router = useRouter()

const isAuthed = computed(() => Boolean(state.token || getToken()))
const showApp = computed(() => isAuthed.value && route.name !== 'login')

// If a token exists but the router is still sitting on the login page (slow
// navigation, a failed async chunk, a back button, a stale token in another tab)
// move forward automatically instead of showing the form again.
watch(
  [isAuthed, () => route.name],
  ([authed, name]) => {
    if (authed && name === 'login') router.replace(landingTarget()).catch(() => window.location.assign('/'))
  },
  { immediate: true },
)

function landingTarget() {
  const raw = route.query.next
  const next = typeof raw === 'string' ? raw : ''
  return next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

function goHome() {
  router.replace('/').catch(() => window.location.assign('/'))
}

let booted = false
onMounted(async () => {
  if (!isAuthed.value) return
  booted = true
  if (route.name === 'login') return // the watcher above is already navigating
  await bootstrap().catch(() => {})
  startLive()
})
onUnmounted(() => stopLive())
</script>
