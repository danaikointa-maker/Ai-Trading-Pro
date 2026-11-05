<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">System & Audit</h1>
        <p class="text-[11px] text-muted">สถานะทุก service, โมเดล, audit trail และ error log</p>
      </div>
      <button class="btn ml-auto py-1.5" @click="load">Refresh</button>
    </header>

    <div class="grid grid-cols-2 gap-2 md:grid-cols-4">
      <Stat label="Status" :value="health?.status || '—'" :tone="health?.status === 'ok' ? 'text-up' : 'text-amber-300'" />
      <Stat label="Uptime" :value="`${fmt(health?.uptime_seconds, 0)}s`" :hint="health?.env" />
      <Stat label="Feed mode" :value="health?.feed_mode || '—'" :hint="`virtual ${clock(health?.virtual_time)}`" />
      <Stat label="Model" :value="model?.version || 'baseline'" :hint="model?.approved ? 'approved' : 'unapproved'" />
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <section class="panel">
        <div class="panel-head"><div class="panel-title">Services</div></div>
        <dl class="px-4 py-3">
          <div v-for="(v, k) in health?.services || {}" :key="k" class="kv">
            <dt>{{ k }}</dt>
            <dd><span class="chip" :class="String(v).includes('ok') || String(v).includes('running') || String(v).includes('approved') ? 'chip-up' : 'chip-warn'">{{ v }}</span></dd>
          </div>
          <div v-for="(v, k) in health?.broker_health || {}" :key="`b-${k}`" class="kv">
            <dt>broker · {{ k }}</dt>
            <dd><span class="chip" :class="v === 'connected' ? 'chip-up' : 'chip-down'">{{ v }}</span></dd>
          </div>
        </dl>
      </section>

      <section class="panel">
        <div class="panel-head"><div class="panel-title">Model registry</div><span class="chip">{{ models.length }} versions</span></div>
        <div class="max-h-[260px] overflow-auto">
          <table class="table-base">
            <thead><tr><th>Version</th><th>Horizons</th><th>Created</th><th>Approved</th></tr></thead>
            <tbody>
              <tr v-for="m in models" :key="m.version">
                <td class="num text-[10.5px]">{{ m.version }}</td>
                <td class="num text-[10px]">{{ (m.horizons || []).join(", ") }}</td>
                <td class="num text-[10px] text-muted">{{ datetime(m.created_at) }}</td>
                <td><span class="chip" :class="m.approved ? 'chip-up' : 'chip-warn'">{{ m.approved ? 'approved' : 'rejected' }}</span></td>
              </tr>
              <tr v-if="!models.length"><td colspan="4" class="py-4 text-center text-[11px] text-muted">ยังไม่มีโมเดล</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section class="panel">
        <div class="panel-head"><div class="panel-title">Audit log</div><span class="chip">most recent 60</span></div>
        <div class="max-h-[380px] overflow-auto">
          <table class="table-base">
            <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>
              <tr v-for="a in audit" :key="a.id">
                <td class="num text-[10px] text-muted">{{ clock(a.t) }}</td>
                <td class="text-[10.5px]">{{ a.actor }}</td>
                <td class="num text-[10.5px] text-gold-400/90">{{ a.action }}</td>
                <td class="max-w-[420px] truncate text-[10px] text-muted" :title="a.detail">{{ a.detail }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div class="space-y-3">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">Errors</div><span class="chip">{{ errors.length }}</span></div>
          <div class="max-h-[200px] space-y-2 overflow-auto px-3 py-2">
            <div v-for="(e, i) in errors" :key="i" class="rounded border border-down/25 bg-down/5 px-2 py-1.5">
              <div class="num text-[10px] text-down">{{ e.where }}</div>
              <p class="text-[10px] text-muted">{{ e.error }}</p>
            </div>
            <p v-if="!errors.length" class="py-4 text-center text-[11px] text-muted">ไม่มี error</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div class="panel-title">Paths & config</div></div>
          <dl class="px-4 py-3 text-[10.5px]">
            <div v-for="(p, k) in config?.public?.paths || {}" :key="k" class="kv">
              <dt>{{ k }}</dt><dd class="num max-w-[190px] truncate text-[10px]" :title="p">{{ p }}</dd>
            </div>
            <div class="kv"><dt>API docs</dt><dd><a class="text-gold-400" href="/api/docs" target="_blank">/api/docs</a></dd></div>
            <div class="kv"><dt>Auth</dt><dd class="text-[10px]">{{ config?.security?.require_auth ? 'JWT required' : 'open (dev)' }}</dd></div>
          </dl>
        </section>
      </div>
    </div>

    <section class="panel border-amber-400/25">
      <div class="panel-head"><div class="panel-title">ข้อจำกัดที่ต้องเข้าใจก่อนใช้งานจริง</div></div>
      <ul class="grid gap-1.5 px-4 py-3 text-[10.5px] leading-relaxed text-muted sm:grid-cols-2">
        <li>• ไม่มี AI ใดพยากรณ์กราฟได้แม่นยำ 100% — ระบบนี้วัดความแม่นยำและยอมรับว่า “ไม่ควรเทรด” ได้</li>
        <li>• Signal Score ไม่เท่ากับความน่าจะเป็นชนะ ต้องดู probability ที่สอบเทียบแยก</li>
        <li>• Full Auto ถูกล็อกไว้ ต้องเปิด ENV + risk toggle + โมเดลที่ผ่าน OOS และบัญชี Demo</li>
        <li>• ข้อมูล feed ในเครื่องนี้เป็น simulated — ผลทดสอบไม่ควรใช้ตัดสินใจกับเงินจริง</li>
        <li>• Connext/FSA และ ธปท.: ตรวจสอบสถานะทางกฎหมายก่อนฝากเงินจริง เริ่มจาก Demo เท่านั้น</li>
        <li>• ควรทำ Walk-forward / Out-of-sample / Paper trading อย่างน้อยหลายสัปดาห์ก่อนเพิ่มทุน</li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import Stat from '../components/Stat.vue'
import { api } from '../lib/api'
import { clock, datetime, fmt } from '../lib/format'
import { state, toast } from '../lib/store'

const health = ref(null)
const audit = ref([])
const errors = ref([])
const models = ref([])
const config = ref(null)

async function load() {
  try {
    const [h, a, m] = await Promise.all([
      api.get('/api/system/health'),
      api.get('/api/system/audit?limit=60'),
      api.get('/api/forecast'),
    ])
    health.value = h
    audit.value = a.audit || []
    models.value = m.models || []
    config.value = state.config
  } catch (err) {
    toast(err.message, 'error')
  }
  errors.value = state.live?.errors || []
}

onMounted(load)
</script>
