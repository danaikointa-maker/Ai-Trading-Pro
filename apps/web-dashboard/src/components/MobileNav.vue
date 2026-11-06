<template>
  <!-- Bottom tab bar: the desktop sidebar is hidden below lg, so without this the
       app is stuck on one screen on a phone. -->
  <nav
    class="fixed inset-x-0 bottom-0 z-40 border-t border-ink-700/70 bg-ink-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
  >
    <div class="mx-auto flex max-w-[1700px] items-stretch">
      <RouterLink
        v-for="item in primaryNav"
        :key="item.to"
        :to="item.to"
        class="flex flex-1 flex-col items-center gap-1 py-2 text-[10px] font-medium transition"
        :class="isActive(item.to) ? 'text-gold-400' : 'text-muted'"
      >
        <span v-html="item.icon" class="grid h-5 w-5 place-items-center" />
        <span>{{ item.short }}</span>
      </RouterLink>
      <button
        class="flex flex-1 flex-col items-center gap-1 py-2 text-[10px] font-medium transition"
        :class="sheetOpen ? 'text-gold-400' : 'text-muted'"
        @click="sheetOpen = true"
      >
        <span class="grid h-5 w-5 place-items-center">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" class="h-4 w-4">
            <path d="M4 7h16M4 12h16M4 17h16" />
          </svg>
        </span>
        <span>เมนู</span>
        <span v-if="alerts" class="absolute right-[18%] top-1.5 h-1.5 w-1.5 rounded-full bg-down" />
      </button>
    </div>
  </nav>

  <!-- Full menu sheet -->
  <transition name="sheet">
    <div v-if="sheetOpen" class="fixed inset-0 z-50 lg:hidden" @click.self="sheetOpen = false">
      <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="sheetOpen = false" />
      <div
        class="absolute inset-x-0 bottom-0 max-h-[82vh] overflow-y-auto rounded-t-2xl border-t border-ink-700 bg-ink-950 px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3"
      >
        <div class="mx-auto mb-3 h-1 w-10 rounded-full bg-ink-700" />
        <div class="mb-3 flex items-center justify-between">
          <div>
            <div class="text-[13px] font-semibold text-slate-100">เมนูทั้งหมด</div>
            <div class="text-[10.5px] text-muted">
              {{ state.connected ? 'เชื่อมต่ออยู่' : 'กำลังเชื่อมต่อใหม่' }} · feed {{ state.live?.feed || '—' }}
            </div>
          </div>
          <button class="rounded-lg border border-ink-700 px-2.5 py-1 text-[11px] text-muted" @click="sheetOpen = false">
            ปิด
          </button>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <RouterLink
            v-for="item in nav"
            :key="item.to"
            :to="item.to"
            class="flex items-center gap-2 rounded-xl border px-3 py-2.5 text-[12px] font-medium transition"
            :class="isActive(item.to)
              ? 'border-gold-500/40 bg-gold-500/10 text-gold-400'
              : 'border-ink-700/70 bg-ink-900 text-slate-300'"
            @click="sheetOpen = false"
          >
            <span v-html="item.icon" class="grid h-4 w-4 place-items-center opacity-80" />
            <span class="flex-1">{{ item.short }}</span>
          </RouterLink>
        </div>
        <div class="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/5 p-3 text-[10.5px] leading-relaxed text-amber-200/80">
          Demo / paper account · ระบบเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { nav, primaryNav } from '../lib/nav'
import { state } from '../lib/store'

const route = useRoute()
const sheetOpen = ref(false)

const isActive = (to) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
const alerts = computed(() => (state.live?.alerts || []).length)

watch(() => route.fullPath, () => { sheetOpen.value = false })
</script>

<style scoped>
.sheet-enter-active, .sheet-leave-active { transition: opacity .18s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
</style>
