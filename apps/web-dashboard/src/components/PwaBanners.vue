<template>
  <div>
    <!-- A new build is waiting. Never swap it silently: the user decides when to
         reload, because reloading closes any half-filled order ticket. -->
    <div v-if="pwa.updateReady"
         class="flex flex-wrap items-center justify-center gap-2 bg-sky-500/15 px-3 py-1.5 text-[11px] font-medium text-sky-300">
      <span class="h-1.5 w-1.5 rounded-full bg-sky-400"></span>
      มีเวอร์ชันใหม่ของแอปแล้ว
      <button class="rounded border border-sky-500/40 px-2 py-0.5 text-[10.5px] font-semibold
                     text-sky-200 hover:bg-sky-500/15" @click="applyUpdate">
        รีเฟรชเดี๋ยวนี้
      </button>
      <button class="text-[10.5px] text-sky-300/70 underline decoration-dotted"
              @click="pwa.updateReady = false">ไว้ภายหลัง</button>
    </div>

    <!-- Install invitation. Shown once, remembered when dismissed, hidden when the
         app is already running from the home screen. -->
    <div v-if="showInstall" class="border-b border-ink-700/60 bg-ink-900/80 px-3 py-2">
      <div class="mx-auto flex max-w-[1700px] flex-wrap items-center gap-x-3 gap-y-2">
        <img src="/icon-192.png" alt="" class="h-7 w-7 rounded-lg" />
        <div class="min-w-0 flex-1">
          <div class="text-[12px] font-semibold text-slate-100">ติดตั้ง No7 เป็นแอป</div>
          <div class="text-[10.5px] leading-relaxed text-muted">
            <template v-if="pwa.canInstall">
              เปิดจากหน้าจอโฮมได้เต็มจอ ไม่ต้องพิมพ์ URL — ข้อมูลราคายังมาจากเซิร์ฟเวอร์เสมอ
            </template>
            <template v-else>
              เปิด Safari → ปุ่ม <span class="text-slate-300">แชร์</span> →
              <span class="text-slate-300">เพิ่มไปที่หน้าจอโฮม</span>
            </template>
          </div>
        </div>
        <button v-if="pwa.canInstall"
                class="rounded-lg bg-gold-500 px-3 py-1.5 text-[11px] font-bold text-ink-950
                       hover:bg-gold-400"
                @click="install">
          ติดตั้ง
        </button>
        <button class="text-[10.5px] text-muted underline decoration-dotted hover:text-slate-300"
                @click="dismissInstall">ไม่ใช่ตอนนี้</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { pwa, applyUpdate, dismissInstall, promptInstall } from '../lib/pwa'

const showInstall = computed(() =>
  !pwa.installed && !pwa.dismissed && (pwa.canInstall || pwa.iosHint))

async function install() {
  const accepted = await promptInstall()
  if (!accepted) dismissInstall()
}
</script>
