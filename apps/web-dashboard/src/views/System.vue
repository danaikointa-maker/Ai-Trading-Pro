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
        <div class="panel-head">
          <div class="panel-title">แอป / PWA</div>
          <span class="chip" :class="pwa.installed ? 'chip-up' : 'chip-warn'">
            {{ pwa.installed ? 'ติดตั้งแล้ว' : 'เปิดในเบราว์เซอร์' }}
          </span>
        </div>
        <dl class="px-4 py-3">
          <div class="kv">
            <dt>service worker</dt>
            <dd>
              <span class="chip" :class="workerReady ? 'chip-up' : 'chip-warn'">
                {{ workerReady ? 'active' : 'ไม่ทำงาน (dev/ยังไม่โหลด)' }}
              </span>
              <span v-if="pwa.updateReady" class="chip chip-warn ml-1">มีเวอร์ชันใหม่</span>
            </dd>
          </div>
          <div class="kv">
            <dt>แคชเชลล์</dt>
            <dd class="num text-[10.5px]">
              <template v-if="pwa.storageUsedMb !== null">
                {{ pwa.storageUsedMb }} MB / {{ pwa.storageQuotaMb }} MB
              </template>
              <span v-else class="text-muted">—</span>
              <span class="ml-2 chip" :class="pwa.storagePersisted ? 'chip-up' : 'chip-warn'">
                {{ pwa.storagePersisted === null ? 'ไม่ทราบ'
                   : pwa.storagePersisted ? 'persist แล้ว' : 'ยังไม่ persist' }}
              </span>
            </dd>
          </div>
          <div class="kv">
            <dt>ติดตั้ง</dt>
            <dd class="flex flex-wrap items-center gap-1.5">
              <button v-if="pwa.canInstall" class="btn py-1 text-[10.5px]" @click="installNow">
                ติดตั้งแอป
              </button>
              <span v-else-if="pwa.installed" class="text-[10.5px] text-muted">
                เปิดจากหน้าจอโฮมอยู่แล้ว
              </span>
              <span v-else class="text-[10.5px] text-muted">
                ใช้เมนูเบราว์เซอร์ → ติดตั้ง (หรือแชร์ → เพิ่มไปที่หน้าจอโฮม บน iOS)
              </span>
            </dd>
          </div>
          <div class="kv">
            <dt>ข้อมูลสด</dt>
            <dd class="text-[10.5px]">
              <span class="chip" :class="state.serverUnreachable ? 'chip-down' : 'chip-up'">
                {{ state.serverUnreachable ? 'เซิร์ฟเวอร์ไม่ตอบ' : 'เชื่อมต่อปกติ' }}
              </span>
              <span class="ml-1 text-muted">/api และ /ws ไม่ถูกแคชเด็ดขาด</span>
            </dd>
          </div>
        </dl>
      </section>

      <section class="panel lg:col-span-2">
        <div class="panel-head">
          <div class="panel-title">ทำไมถึงไม่เทรด (Decision attribution)</div>
          <span class="chip" :class="attributionTone">{{ attributionChip }}</span>
          <div class="ml-auto flex items-center gap-1">
            <button
              v-for="w in WINDOWS" :key="w.seconds"
              class="rounded px-1.5 py-0.5 text-[10px] transition"
              :class="w.seconds === windowSeconds
                ? 'bg-accent/20 font-semibold text-accent'
                : 'text-muted hover:text-slate-200'"
              @click="setWindow(w.seconds)"
            >{{ w.label }}</button>
            <button class="btn py-1 text-[10.5px]" :disabled="resetting" @click="resetAttribution">
              เริ่มนับใหม่
            </button>
          </div>
        </div>
        <div class="px-4 py-3">
          <p class="text-[11px] text-slate-200">{{ attribution?.headline || 'ยังไม่มีการตัดสินใจในหน้าต่างนี้' }}</p>
          <p class="mt-1 text-[10px] text-muted">
            <template v-if="attribution?.basis === 'rolling'">
              {{ fmt((attribution?.window_seconds || 0) / 60, 0) }} นาทีล่าสุด
              (ตั้งแต่ {{ datetime(attribution?.window_since) }}) ·
              ทั้งเซสชัน {{ sessionDecisions }} การตัดสินใจ ตั้งแต่ {{ datetime(attribution?.since) }}
            </template>
            <template v-else>
              ทั้งเซสชันตั้งแต่ {{ datetime(attribution?.since) }}
              ({{ fmt((attribution?.window_seconds || 0) / 60, 0) }} นาที)
            </template>
            · {{ (attribution?.symbols || []).join(', ') || '—' }}
          </p>
          <p v-if="idleNote" class="mt-1 text-[10px] text-amber-300">{{ idleNote }}</p>

          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <div>
              <div class="mb-1 flex items-baseline justify-between">
                <span class="text-[10.5px] font-semibold text-slate-200">สัญญาณที่ไม่ผ่าน</span>
                <span class="num text-[10px] text-muted">
                  {{ signalPart.blocked }} / {{ signalPart.decisions }} ครั้ง
                </span>
              </div>
              <div v-if="!signalPart.primary.length" class="text-[10.5px] text-muted">ยังไม่มีข้อมูล</div>
              <div v-for="row in signalPart.primary" :key="row.code" class="mb-1.5">
                <div class="flex items-baseline justify-between gap-2">
                  <span class="truncate text-[10.5px] text-slate-200" :title="row.samples.join(' · ')">{{ row.label }}</span>
                  <span class="num shrink-0 text-[10px] text-muted">{{ row.count }} · {{ row.pct }}%</span>
                </div>
                <div class="mt-0.5 h-1 rounded bg-slate-800">
                  <div class="h-1 rounded bg-amber-400/80" :style="{ width: `${Math.min(100, row.pct)}%` }"></div>
                </div>
              </div>
            </div>

            <div>
              <div class="mb-1 flex items-baseline justify-between">
                <span class="text-[10.5px] font-semibold text-slate-200">Risk gate ปัดสัญญาณที่พร้อมเทรด</span>
                <span class="num text-[10px] text-muted">
                  {{ gatePart.blocked }} / {{ gatePart.evaluated }} ครั้ง
                </span>
              </div>
              <div v-if="!gatePart.primary.length" class="text-[10.5px] text-muted">
                ไม่มีสัญญาณไหนถูก gate ปัดในหน้าต่างนี้
              </div>
              <div v-for="row in gatePart.primary" :key="row.code" class="mb-1.5">
                <div class="flex items-baseline justify-between gap-2">
                  <span class="truncate text-[10.5px] text-slate-200" :title="row.samples.join(' · ')">{{ row.label }}</span>
                  <span class="num shrink-0 text-[10px] text-muted">{{ row.count }} · {{ row.pct }}%</span>
                </div>
                <div class="mt-0.5 h-1 rounded bg-slate-800">
                  <div class="h-1 rounded bg-rose-400/80" :style="{ width: `${Math.min(100, row.pct)}%` }"></div>
                </div>
              </div>
            </div>
          </div>

          <p v-if="attribution?.overall?.warning" class="mt-2 text-[10px] text-amber-300">
            {{ attribution.overall.warning }}
          </p>
          <p class="mt-2 text-[9.5px] text-muted">
            primary = เหตุผลที่ผูกมัดที่สุดต่อหนึ่งการตัดสินใจ (รวมกันได้เท่าจำนวนที่ถูกบล็อก) ·
            ชี้ที่ชื่อเหตุผลเพื่อดูตัวอย่างข้อความจริง
          </p>
        </div>
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

        <section v-if="bridge" class="panel">
          <div class="panel-head">
            <div class="panel-title">EA bridge (MT5)</div>
            <span class="chip" :class="bridge.enabled ? (anyFresh ? 'chip-up' : 'chip-warn') : 'chip-down'">
              {{ bridge.enabled ? (anyFresh ? 'EA connected' : 'no EA') : 'disabled' }}
            </span>
          </div>
          <dl class="grid gap-1 px-3 py-2 text-[11px]">
            <div v-for="b in bridge.bridges" :key="b.account" class="grid grid-cols-[1fr_auto] items-center gap-2">
              <div class="min-w-0">
                <div class="truncate text-[10.5px] font-semibold">{{ b.broker_id }}</div>
                <div class="num truncate text-[9.5px] text-muted">
                  {{ b.session_id || 'no session' }}
                  <span v-if="b.snapshot_age_seconds != null"> · snapshot {{ b.snapshot_age_seconds.toFixed(1) }}s</span>
                  <span v-else> · ยังไม่มีข้อมูลจาก terminal</span>
                </div>
              </div>
              <span class="chip" :class="b.health === 'connected' ? 'chip-up' : (b.health === 'stale' ? 'chip-warn' : 'chip-down')">
                {{ b.health }}
              </span>
            </div>
            <div v-if="!bridge.bridges?.length" class="text-[10px] text-muted">ยังไม่มี broker profile แบบ bridge</div>
            <p class="mt-1 text-[9px] leading-relaxed text-muted">
              ข้อมูลราคาและพอร์ตมาจาก snapshot ของ EA ทั้งหมด — เก่ากว่า
              {{ bridge.stale_seconds }}s ระบบจะไม่ยอมใช้ (ไม่มีการเดาราคาเก่า)
              และคำสั่งที่ EA ไม่รับภายในเวลาที่กำหนดจะหมดอายุ ไม่ส่งซ้ำ
            </p>
            <p v-if="bridge.enabled && !anyFresh" class="text-[9.5px] leading-relaxed text-amber-300/80">
              ยังไม่มี EA ต่อเข้ามา — เปิด MT5 แล้วรัน bridge/No7BridgeEA.mq5
              (หรือทดสอบด้วย scripts/run_bridge_sim.py) ก่อนสั่งเทรดผ่าน broker นี้
            </p>
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
import { pwa, promptInstall, refreshStorageEstimate } from '../lib/pwa'

const health = ref(null)
const workerReady = ref(false)

async function installNow() {
  const accepted = await promptInstall()
  if (accepted) toast('ติดตั้งแอปเรียบร้อย', 'success')
}
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
const bridge = ref(null)
const anyFresh = computed(() =>
  (bridge.value?.bridges || []).some((b) => b.health === 'connected'))
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
const attribution = ref(null)
const resetting = ref(false)
// Cumulative-since-boot was the only view on offer, which answers "what has
// stopped this engine on average since Tuesday" — never "why is it quiet now".
const WINDOWS = [
  { label: '15น', seconds: 900 },
  { label: '1ชม', seconds: 3600 },
  { label: '6ชม', seconds: 21600 },
  { label: 'ทั้งหมด', seconds: 0 },
]
const windowSeconds = ref(3600)
const sessionDecisions = computed(() => attribution.value?.session?.signal?.decisions ?? 0)
// An empty table because nothing was decided is a different fact from an empty
// table because everything passed; the panel must never let them look alike.
const idleNote = computed(() => {
  const a = attribution.value
  if (!a || a.basis !== 'rolling' || a.overall?.signal?.decisions) return ''
  if (!a.idle_seconds) return ''
  return `เงียบ: ไม่มีการตัดสินใจในหน้าต่างนี้ ล่าสุดเมื่อ ${fmt(a.idle_seconds / 60, 0)} นาทีก่อน`
    + ` — ลองขยายหน้าต่างเพื่อดูว่าติดอะไรอยู่`
})
const EMPTY_SIGNAL = { decisions: 0, actionable: 0, blocked: 0, primary: [], fired: [] }
const EMPTY_GATE = { evaluated: 0, allowed: 0, blocked: 0, primary: [], fired: [] }
const signalPart = computed(() => attribution.value?.overall?.signal || EMPTY_SIGNAL)
const gatePart = computed(() => attribution.value?.overall?.gate || EMPTY_GATE)
// A quiet terminal has two very different causes: nothing qualified, or one
// rule rejected everything. The chip says which, without opening the panel.
const attributionChip = computed(() => {
  const s = signalPart.value
  if (!s.decisions) return 'ยังไม่มีข้อมูล'
  if (s.actionable) return `${s.actionable}/${s.decisions} พร้อมเทรด`
  const top = s.primary[0]
  return top ? `0 พร้อมเทรด · ${top.label}` : `0/${s.decisions} พร้อมเทรด`
})
const attributionTone = computed(() => {
  const s = signalPart.value
  if (!s.decisions) return 'chip-warn'
  return s.actionable ? 'chip-up' : 'chip-warn'
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

async function setWindow(seconds) {
  windowSeconds.value = seconds
  await loadAttribution()
}

async function loadAttribution() {
  try {
    attribution.value = await api.get(`/api/system/attribution?window=${windowSeconds.value}`)
  } catch {
    attribution.value = null  // older server without attribution: panel stays empty
  }
}

async function resetAttribution() {
  if (resetting.value) return
  resetting.value = true
  try {
    await api.post('/api/system/attribution/reset')
    // Re-read rather than trusting the POST body: it answers for the default
    // window and the operator may be looking at a different one.
    await loadAttribution()
    toast('เริ่มนับเหตุผลใหม่แล้ว', 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    resetting.value = false
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
  try {
    bridge.value = await api.get('/api/bridge/session')
  } catch {
    bridge.value = null   // older server without the bridge: the card simply hides
  }
  await loadAttribution()
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
