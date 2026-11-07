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
      <Stat label="Feed mode" :value="health?.feed_mode || '—'" :hint="feedHint" :tone="feedTone" />
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
          <div class="kv">
            <dt>cluster</dt>
            <dd class="flex flex-wrap items-center gap-1.5">
              <span class="chip" :class="clusterTone" :title="clusterTitle">{{ clusterRole }}</span>
              <span class="num text-[9.5px] text-muted">{{ cluster?.backend }}</span>
              <span v-if="cluster?.reason" class="chip chip-warn" :title="cluster.reason">fallback</span>
            </dd>
          </div>
          <div class="kv">
            <dt>runtime lease</dt>
            <dd>
              <span class="chip" :class="leaseTone" :title="leaseTitle">{{ leaseLabel }}</span>
            </dd>
          </div>
          <div v-if="health?.feed_note" class="kv">
            <dt>feed note</dt>
            <dd><span class="chip chip-warn" :title="health.feed_note">{{ shortNote }}</span></dd>
          </div>
          <div v-for="(v, k) in feedSymbols" :key="`f-${k}`" class="kv">
            <dt>feed · {{ k }}</dt>
            <dd class="num text-[10px]">
              {{ v.bars_replayed }}/{{ v.bars_total - v.warmup_bars }} bars
              <span class="text-muted">({{ Math.round((v.progress || 0) * 100) }}%)</span>
              <span v-if="v.exhausted" class="chip chip-warn ml-1">exhausted</span>
            </dd>
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
          <div class="panel-head">
            <div class="panel-title">ช่องทางแจ้งเตือน</div>
            <span class="chip" :class="notifyTone">{{ notifyLabel }}</span>
          </div>
          <dl class="px-4 py-3 text-[10.5px]">
            <div v-for="(c, name) in notify?.channels || {}" :key="name" class="kv">
              <dt>{{ name }}</dt>
              <dd class="flex items-center gap-1.5">
                <span class="chip" :class="c.configured ? (c.ok === false ? 'chip-down' : 'chip-up') : 'chip-warn'">
                  {{ c.configured ? (c.ok === false ? 'failing' : 'ready') : 'off' }}
                </span>
                <span v-if="c.configured && c.failures" class="num text-[9.5px] text-down">{{ c.failures }} fails</span>
                <span v-if="c.configured && c.error" class="max-w-[170px] truncate text-[9.5px] text-down" :title="c.error">{{ c.error }}</span>
                <span v-if="c.last_attempt" class="num text-[9.5px] text-muted">{{ clock(c.last_attempt) }}</span>
              </dd>
            </div>
            <p v-if="notify?.disabled_reason" class="mt-2 text-[9.5px] leading-relaxed text-amber-300/80">
              {{ notify.disabled_reason }}
            </p>
            <button class="btn mt-2 w-full py-1 text-[10px]" :disabled="testing" @click="sendTest">
              {{ testing ? 'กำลังส่ง…' : 'ส่งข้อความทดสอบ' }}
            </button>
          </dl>
        </section>

        <section v-if="perms.canManageUsers" class="panel">
          <div class="panel-head">
            <div class="panel-title">ผู้ใช้และสิทธิ์</div>
            <span class="chip">{{ users.length }} accounts</span>
          </div>
          <div class="max-h-[220px] overflow-auto">
            <table class="table-base">
              <thead><tr><th>Email</th><th>Role</th><th>สถานะ</th><th></th></tr></thead>
              <tbody>
                <tr v-for="u in users" :key="u.email">
                  <td class="text-[10.5px]">{{ u.email }}</td>
                  <td>
                    <select class="input py-0.5 text-[10px]" :value="u.role"
                            @change="setRole(u, $event.target.value)">
                      <option v-for="r in roles" :key="r.role" :value="r.role" :title="r.description">{{ r.role }}</option>
                    </select>
                  </td>
                  <td>
                    <span class="chip" :class="u.active ? 'chip-up' : 'chip-down'">{{ u.active ? 'active' : 'disabled' }}</span>
                  </td>
                  <td class="text-right">
                    <button class="btn px-1.5 py-0.5 text-[9.5px]" :disabled="u.email === me"
                            :title="u.email === me ? 'ลบบัญชีที่ใช้อยู่ไม่ได้' : 'ลบผู้ใช้'"
                            @click="removeUser(u)">ลบ</button>
                  </td>
                </tr>
                <tr v-if="!users.length"><td colspan="4" class="py-3 text-center text-[11px] text-muted">ยังไม่มีผู้ใช้</td></tr>
              </tbody>
            </table>
          </div>
          <div class="grid gap-1.5 border-t border-ink-700/60 px-3 py-2">
            <div class="grid grid-cols-[1fr_1fr_auto_auto] items-end gap-1.5">
              <label class="text-[9.5px] text-muted">อีเมล<input v-model="newUser.email" class="input mt-0.5 py-1 text-[10px]" placeholder="user@example.com" /></label>
              <label class="text-[9.5px] text-muted">รหัสผ่าน (≥8)<input v-model="newUser.password" type="password" class="input mt-0.5 py-1 text-[10px]" /></label>
              <select v-model="newUser.role" class="input py-1 text-[10px]">
                <option v-for="r in roles" :key="r.role" :value="r.role">{{ r.role }}</option>
              </select>
              <button class="btn py-1 text-[10px]" :disabled="busy" @click="addUser">เพิ่ม</button>
            </div>
            <p class="text-[9px] leading-relaxed text-muted">
              admin &gt; trader &gt; viewer · การเปลี่ยน role/ปิดบัญชีมีผลกับ token ที่ใช้งานอยู่ทันที
              · ระบบไม่ยอมให้ปิด admin ที่ยังใช้งานคนสุดท้าย
            </p>
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
        <li>• {{ feedLimitation }}</li>
        <li>• Connext/FSA และ ธปท.: ตรวจสอบสถานะทางกฎหมายก่อนฝากเงินจริง เริ่มจาก Demo เท่านั้น</li>
        <li>• ควรทำ Walk-forward / Out-of-sample / Paper trading อย่างน้อยหลายสัปดาห์ก่อนเพิ่มทุน</li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import Stat from '../components/Stat.vue'
import { api } from '../lib/api'
import { clock, datetime, fmt } from '../lib/format'
import { permissions, state, toast } from '../lib/store'

const health = ref(null)
// Say what the feed *is*, not what it usually is: simulated, imported replay or live MT5.
const FEED_TEXT = {
  simulated: 'ข้อมูล feed ในเครื่องนี้เป็นข้อมูลจำลอง — ผลทดสอบไม่ควรใช้ตัดสินใจกับเงินจริง',
  replay: 'ข้อมูล feed ในเครื่องนี้เป็น replay จากไฟล์ที่นำเข้า (ไม่ใช่ tick data และไม่ใช่ราคาสด)',
  mt5: 'ข้อมูล feed มาจากเทอร์มินัล MT5 จริง — ยังต้องยืนยันกับตลาดจริงก่อนใช้',
}
const feedLimitation = computed(() => FEED_TEXT[health.value?.feed_mode] || FEED_TEXT.simulated)
const feedTone = computed(() => (health.value?.feed_mode === 'mt5' ? 'text-up' : 'text-amber-300'))
const feedHint = computed(() => {
  const h = health.value
  if (!h) return ''
  if (h.feed_note) return 'fell back — see note'
  const progress = Object.values(h.feed?.symbols || {})
  if (progress.length) {
    const avg = progress.reduce((a, v) => a + (v.progress || 0), 0) / progress.length
    return `replay ${Math.round(avg * 100)}%${h.feed?.exhausted ? ' · exhausted' : ''}`
  }
  return `virtual ${clock(h.virtual_time)}`
})
const feedSymbols = computed(() => health.value?.feed?.symbols || {})

// One process may drive ticks and orders per database. When the lease is held
// elsewhere this page still loads, but nothing moves — say so instead of
// leaving a frozen screen with no explanation.
const cluster = computed(() => health.value?.cluster || {})
const clusterRole = computed(() => {
  const role = cluster.value.role || 'unknown'
  const shared = cluster.value.shared_health
  return shared && shared.ok === false ? `${role} · backend down` : role
})
const clusterTone = computed(() => {
  const role = cluster.value.role
  const down = cluster.value.shared_health?.ok === false
  if (down) return 'chip-down'
  if (role === 'leader') return 'chip-up'
  return role === 'replica' ? 'chip-up' : 'chip-warn'
})
const clusterTitle = computed(() => {
  const c = cluster.value
  if (!c.role) return ''
  const parts = [`backend: ${c.backend || 'local'} (ขอ: ${c.requested || 'local'})`]
  if (c.reason) parts.push(c.reason)
  if (c.shared_health?.error) parts.push(`shared backend: ${c.shared_health.error}`)
  if (c.role === 'replica') parts.push('โปรเซสนี้เสิร์ฟเฟรมของ leader แบบอ่านอย่างเดียว')
  if (c.role === 'blocked') parts.push('ไม่ถือ lease และไม่มี shared backend ให้อ่าน')
  return parts.join(' · ')
})

const lease = computed(() => health.value?.runtime_lease || {})
const leaseLabel = computed(() => {
  const state = lease.value.state || 'unknown'
  const owner = lease.value.owner || '—'
  if (state === 'held' || state === 'shared') return `${state} · ${owner}`
  if (state === 'blocked') return `blocked by ${owner}`
  if (state === 'lost') return `lost to ${owner}`
  if (state === 'released') return 'released'
  return state
})
const leaseTone = computed(() => {
  const state = lease.value.state
  if (state === 'held') return 'chip-up'
  return state === 'shared' ? 'chip-warn' : 'chip-down'
})
const leaseTitle = computed(() => {
  const l = lease.value
  if (l.state === 'held') return ` heartbeat ${fmt(l.heartbeat_age_seconds, 1)}s ago`
  if (l.state === 'shared') return 'NO7_ALLOW_MULTI_RUNTIME เปิดอยู่ — อาจมีออเดอร์ซ้ำ'
  if (l.state === 'blocked') return `runtime อื่นถือฐานข้อมูลนี้อยู่ (heartbeat ${fmt(l.heartbeat_age_seconds, 1)}s) — โปรเซสนี้ไม่เทรด`
  if (l.state === 'lost') return 'มีโปรเซสอื่นยึด runtime ไปแล้ว — โปรเซสนี้หยุดเทรด'
  return ''
})
const shortNote = computed(() => {
  const note = String(health.value?.feed_note || '')
  return note.length > 60 ? `${note.slice(0, 60)}…` : note
})
const audit = ref([])
const users = ref([])
const roles = ref([])
const busy = ref(false)
const newUser = ref({ email: '', password: '', role: 'viewer' })
const perms = computed(() => permissions.value)
const me = computed(() => state.user?.email || '')
const notify = computed(() => health.value?.notify || null)
const testing = ref(false)
const notifyLabel = computed(() => {
  const state_ = notify.value?.state
  if (state_ === 'failing') return `failing · ${(notify.value?.failing || []).join(', ')}`
  if (state_ === 'external') return 'external on'
  return 'in-app only'
})
const notifyTone = computed(() => {
  const state_ = notify.value?.state
  if (state_ === 'failing') return 'chip-down'
  return state_ === 'external' ? 'chip-up' : 'chip-warn'
})
const errors = ref([])
const models = ref([])
const config = ref(null)

async function loadUsers() {
  if (!perms.value.canManageUsers) return
  try {
    const res = await api.get('/api/users')
    users.value = res.users || []
    roles.value = res.roles || []
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function addUser() {
  if (busy.value) return
  busy.value = true
  try {
    await api.post('/api/users', { ...newUser.value })
    toast('เพิ่มผู้ใช้แล้ว', 'success')
    newUser.value = { email: '', password: '', role: 'viewer' }
    await loadUsers()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}

async function setRole(user, role) {
  try {
    await api.patch(`/api/users/${encodeURIComponent(user.email)}`, { role })
    toast(`เปลี่ยน role ของ ${user.email} เป็น ${role}`, 'success')
    await loadUsers()
  } catch (err) {
    toast(err.message, 'error')
    await loadUsers()
  }
}

async function removeUser(user) {
  if (!window.confirm(`ลบผู้ใช้ ${user.email}?`)) return
  try {
    await api.del(`/api/users/${encodeURIComponent(user.email)}`)
    toast('ลบผู้ใช้แล้ว', 'success')
    await loadUsers()
  } catch (err) {
    toast(err.message, 'error')
  }
}

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
  await loadUsers()
}

async function sendTest() {
  if (testing.value) return
  testing.value = true
  try {
    const res = await api.post('/api/system/alerts/test')
    if (res.ok) {
      toast('ส่งทดสอบสำเร็จ — ตรวจข้อความในแอปนั้น', 'success')
    } else if (res.deliveries?.length) {
      const failed = res.deliveries.filter((d) => !d.ok)
      toast(`ส่งไม่สำเร็จ: ${failed.map((d) => `${d.channel} (${d.error})`).join(', ')}`, 'error')
    } else {
      toast(res.reason || 'ยังไม่ได้ตั้งค่าช่องทางภายนอก', 'error')
    }
    await load()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>
