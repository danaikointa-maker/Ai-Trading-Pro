<template>
  <div class="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
    <div class="relative hidden flex-col justify-between overflow-hidden p-10 lg:flex">
      <div class="pointer-events-none absolute -left-24 top-1/3 h-72 w-72 rounded-full bg-gold-500/10 blur-3xl"></div>
      <div class="flex items-center gap-3">
        <div class="grid h-11 w-11 place-items-center rounded-xl bg-gold-500/15 text-[17px] font-black text-gold-400 ring-1 ring-gold-500/30">N7</div>
        <div>
          <div class="text-[15px] font-semibold tracking-wide">NO7 AI TRADING PRO</div>
          <div class="text-[10px] uppercase tracking-[0.22em] text-muted">Hybrid quant · multi-broker · V1</div>
        </div>
      </div>
      <div class="max-w-xl">
        <h1 class="text-[30px] font-semibold leading-tight text-slate-100">
          วิเคราะห์ตลาดแบบ Real-Time<br />
          <span class="text-gold-400">วัดผลได้จริง</span> ก่อนเสี่ยงเงินทุน
        </h1>
        <p class="mt-4 text-[13px] leading-relaxed text-muted">
          Trend & market structure หลาย timeframe · แนวรับ–แนวต้านแบบ Confluence 3–5 ระดับ ·
          พยากรณ์ราคาเป็นช่วง P10–P90 พร้อมโอกาสถึง TP ก่อน SL · Risk Engine ที่ยับยั้งคำสั่งได้เสมอ ·
          ส่งคำสั่งผ่าน MT5 adapter แบบ idempotent
        </p>
        <div class="mt-6 grid grid-cols-2 gap-2.5 text-[11.5px]">
          <div v-for="f in features" :key="f" class="flex items-start gap-2 rounded-lg border border-ink-700/70 bg-ink-850/60 px-3 py-2">
            <span class="mt-0.5 text-gold-400">◆</span><span class="text-slate-300">{{ f }}</span>
          </div>
        </div>
      </div>
      <p class="max-w-xl text-[10.5px] leading-relaxed text-muted">
        ระบบนี้เป็นเครื่องมือเพื่อการศึกษาและทดลอง ไม่ใช่คำแนะนำการลงทุน และไม่มีการรับประกันผลกำไร
        เริ่มจากบัญชี Demo เท่านั้นจนกว่าจะตรวจสอบสถานะทางกฎหมายและความคุ้มครองผู้ใช้ในประเทศไทย
      </p>
    </div>

    <div class="flex items-center justify-center px-5 py-10">
      <form class="panel w-full max-w-[400px] p-6" @submit.prevent="submit">
        <div class="mb-1 flex items-center gap-2 lg:hidden">
          <div class="grid h-9 w-9 place-items-center rounded-lg bg-gold-500/15 text-[14px] font-black text-gold-400 ring-1 ring-gold-500/30">N7</div>
          <span class="text-[13px] font-semibold">No7 AI Trading Pro</span>
        </div>
        <h2 class="mt-2 text-[17px] font-semibold text-slate-100">เข้าสู่ระบบ</h2>
        <p class="mt-1 text-[11.5px] text-muted">ใช้บัญชี Demo ที่ระบบสร้างให้ (เก็บรหัสใน .env เท่านั้น)</p>

        <label class="mt-5 block">
          <span class="label">Email</span>
          <input v-model="email" type="email" required autocomplete="username" class="input mt-1" />
        </label>
        <label class="mt-3 block">
          <span class="label">Password</span>
          <input v-model="password" type="password" required autocomplete="current-password" class="input mt-1" />
        </label>

        <button class="btn btn-gold mt-5 w-full py-2.5" :disabled="loading">
          {{ loading ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ' }}
        </button>
        <p v-if="error" class="mt-3 rounded-lg border border-down/30 bg-down/10 px-3 py-2 text-[11px] text-down">{{ error }}</p>

        <div class="mt-5 rounded-lg border border-ink-700 bg-ink-900/60 p-3">
          <div class="label mb-1">Demo credentials</div>
          <div class="num text-[11px] text-slate-300">demo@no7.ai · no7demo1234</div>
          <button type="button" class="mt-2 text-[10.5px] text-gold-400/90 hover:text-gold-400" @click="fillDemo">
            เติมข้อมูลให้อัตโนมัติ
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { bootstrap, login, startLive } from '../lib/store'
import { getToken } from '../lib/api'

const router = useRouter()
const route = useRoute()
const email = ref('demo@no7.ai')
const password = ref('no7demo1234')
const loading = ref(false)
const error = ref('')

const features = [
  'Trend / structure / BOS·CHoCH หลาย TF',
  'โซนแนวรับ–แนวต้าน Confluence ≥ 3 หลักฐานอิสระ',
  'Forecast 3 สถานการณ์ + P10–P90',
  'TP 500–1,000 points แบบ Adaptive',
  'Risk Engine: lot จากระยะ SL, daily kill switch',
  'Broker adapter: Connext / MT5 generic',
]

function fillDemo() {
  email.value = 'demo@no7.ai'
  password.value = 'no7demo1234'
}

function landingTarget() {
  const raw = route.query.next
  const next = typeof raw === 'string' ? raw : ''
  return next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

async function submit() {
  loading.value = true
  error.value = ''
  try {
    await login(email.value, password.value)
    // Leave the login route immediately: waiting for bootstrap() first left the
    // user staring at the form (with a valid token already stored) whenever the
    // bootstrap calls were slow.
    await router.replace(landingTarget()).catch(() => window.location.assign('/'))
    bootstrap().catch(() => {})
    startLive()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (route.query.demo === '1') fillDemo()
  // A reload on /login with a live token must not keep the form on screen.
  if (getToken()) router.replace(landingTarget()).catch(() => window.location.assign('/'))
})
</script>
