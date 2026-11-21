<template>
  <div class="space-y-3">
    <header class="flex flex-wrap items-end gap-2">
      <div>
        <h1 class="text-[16px] font-semibold text-slate-100">Broker Manager</h1>
        <p class="text-[11px] text-muted">แยก broker account ต่อ owner/team และตรวจสิทธิ์จาก server ทุกครั้ง</p>
      </div>
      <button class="btn ml-auto py-1.5" @click="load">Refresh</button>
    </header>

    <section v-if="isPlatformSuperAdmin" class="panel border-amber-400/25 p-4 text-[11px] text-muted">
      Platform super admin is limited to tenant administration and has no broker or trading access.
    </section>

    <template v-else>
    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">Managed broker accounts</div>
        <span class="chip chip-warn">Demo validation pending · execution disabled</span>
      </div>
      <form v-if="state.user?.role !== 'viewer'" class="grid gap-2 border-b border-ink-700/60 p-3 md:grid-cols-3 xl:grid-cols-8" @submit.prevent="createManagedAccount">
        <label class="text-[9.5px] text-muted">Provider
          <select v-model="accountForm.provider" class="input mt-0.5 py-1.5 text-[10px]"><option value="mt5">MetaTrader 5</option></select>
        </label>
        <label class="text-[9.5px] text-muted">Label
          <input v-model="accountForm.label" class="input mt-0.5 py-1.5 text-[10px]" required maxlength="100" placeholder="Connext Demo 1" />
        </label>
        <label class="text-[9.5px] text-muted">Server
          <input v-model="accountForm.server" class="input mt-0.5 py-1.5 text-[10px]" required placeholder="Broker-Demo" />
        </label>
        <label class="text-[9.5px] text-muted">Account type
          <select v-model="accountForm.account_type" class="input mt-0.5 py-1.5 text-[10px]"><option value="demo">Demo</option><option value="live">Live (disabled)</option></select>
        </label>
        <label class="text-[9.5px] text-muted">Broker login
          <input v-model="accountForm.login" class="input mt-0.5 py-1.5 text-[10px]" required autocomplete="off" />
        </label>
        <label class="text-[9.5px] text-muted">Broker password
          <input v-model="accountForm.password" type="password" class="input mt-0.5 py-1.5 text-[10px]" required autocomplete="new-password" />
        </label>
        <label class="text-[9.5px] text-muted">MT5 terminal path
          <input v-model="accountForm.terminal_path" class="input mt-0.5 py-1.5 text-[10px]" placeholder="C:\Program Files\MetaTrader 5\terminal64.exe" />
        </label>
        <label class="text-[9.5px] text-muted">Validation symbol
          <input v-model="accountForm.validation_symbol" class="input mt-0.5 py-1.5 text-[10px]" required placeholder="XAUUSD" />
        </label>
        <button class="btn py-1.5 text-[10px] md:col-span-3 xl:col-span-8" :disabled="creatingAccount">
          {{ creatingAccount ? 'Saving encrypted credentials…' : 'Add account record' }}
        </button>
      </form>
      <p class="border-b border-ink-700/60 px-3 py-2 text-[9.5px] leading-relaxed text-muted">
        Credentials are write-only and encrypted per account; they are never shown again. Set the vault master key through the OS/secret manager, not `.env`.
        Add does not log in or trade. Demo validation only checks an already-running MT5 terminal and current quote.
      </p>
      <div class="overflow-x-auto">
        <table class="table-base">
          <thead><tr><th>Account</th><th>Owner</th><th>Assignment</th><th>Status</th><th>Access</th><th></th></tr></thead>
          <tbody>
            <template v-for="account in managedAccounts" :key="account.id">
              <tr>
                <td>
                  <div class="font-medium">{{ account.label }} <span class="chip">{{ account.account_type }}</span></div>
                  <div class="num text-[9px] text-muted">{{ account.provider }} · {{ account.server }} · login {{ account.login }}</div>
                </td>
                <td class="text-[10px]">{{ account.owner_email }}</td>
                <td class="text-[10px]">
                  <div>{{ account.assigned_manager_email || 'Unassigned' }}</div>
                  <div v-if="account.assigned_team_id" class="num text-[9px] text-muted">team {{ account.assigned_team_id }}</div>
                </td>
                <td><span class="chip" :class="account.connection_status === 'ready_read_only' ? 'chip-up' : 'chip-warn'">{{ account.connection_status }}</span></td>
                <td>
                  <span class="chip" :class="account.can_control ? 'chip-up' : 'chip-warn'">{{ account.can_control ? 'control' : 'read-only' }}</span>
                  <span class="chip chip-down ml-1">orders off</span>
                </td>
                <td class="text-right">
                  <button v-if="account.account_type === 'demo' && account.can_control && account.terminal_path_configured"
                          class="btn mr-1 py-0.5 text-[9px]" :disabled="validatingAccountId === account.id"
                          @click="validateDemoAccount(account)">
                    {{ validatingAccountId === account.id ? 'กำลังตรวจ…' : 'เชื่อม/ตรวจ MT5 อ่านอย่างเดียว' }}
                  </button>
                  <span v-else-if="account.account_type === 'demo' && account.can_control && !account.terminal_path_configured"
                        class="text-[9px] text-muted">Set terminal path to validate</span>
                  <button v-if="account.assigned_team_id && state.user?.role === 'admin'" class="btn py-0.5 text-[9px]"
                          @click="unassignManagedAccount(account)">คืนให้ owner</button>
                </td>
              </tr>
              <tr v-if="account.can_assign && !account.assigned_team_id && teams.length" :key="`${account.id}-assignment`">
                <td colspan="6">
                  <form class="grid items-end gap-1.5 md:grid-cols-[1fr_1fr_auto]" @submit.prevent="assignManagedAccount(account)">
                    <label class="text-[9px] text-muted">มอบหมายทีม
                      <select v-model="assignmentDrafts[account.id].team_id" class="input mt-0.5 py-1 text-[10px]" required
                              @change="assignmentDrafts[account.id].manager_email = ''">
                        <option value="" disabled>เลือกทีม</option>
                        <option v-for="team in teams" :key="team.id" :value="team.id">{{ team.name }}</option>
                      </select>
                    </label>
                    <label class="text-[9px] text-muted">ผู้ดูแลที่ควบคุมบัญชี
                      <select v-model="assignmentDrafts[account.id].manager_email" class="input mt-0.5 py-1 text-[10px]" required>
                        <option value="" disabled>เลือก team manager</option>
                        <option v-for="member in teamManagers(assignmentDrafts[account.id].team_id)" :key="member.user_email" :value="member.user_email">{{ member.user_email }}</option>
                      </select>
                    </label>
                    <button class="btn py-1 text-[10px]" :disabled="!assignmentDrafts[account.id].manager_email">Assign (owner becomes read-only)</button>
                  </form>
                </td>
              </tr>
            </template>
            <tr v-if="!managedAccounts.length"><td colspan="6" class="py-4 text-center text-[11px] text-muted">ยังไม่มี managed broker account</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="isDefaultTenant" class="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="b in brokers" :key="b.id" class="panel flex flex-col p-3"
               :class="b.id === active ? 'ring-1 ring-gold-500/40' : ''">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-[12.5px] font-semibold text-slate-100">{{ b.label }}</div>
            <div class="num text-[10px] text-muted">{{ b.id }} · {{ b.server }}</div>
          </div>
          <span class="chip" :class="b.health === 'connected' ? 'chip-up' : b.health === 'degraded' ? 'chip-warn' : 'chip-down'">
            {{ b.health }}
          </span>
        </div>
        <dl class="mt-2 text-[10.5px]">
          <div class="kv"><dt>Adapter</dt><dd>{{ b.adapter }}</dd></div>
          <div class="kv"><dt>Type</dt><dd>{{ b.account_type }}</dd></div>
          <div class="kv"><dt>Balance</dt><dd>{{ money(b.account?.balance) }}</dd></div>
          <div class="kv"><dt>Equity</dt><dd>{{ money(b.account?.equity) }}</dd></div>
          <div class="kv"><dt>Leverage</dt><dd>1:{{ b.account?.leverage }}</dd></div>
        </dl>
        <p class="mt-2 line-clamp-3 text-[9.5px] leading-relaxed text-muted">{{ b.regulated_note }}</p>
        <button class="btn mt-2 w-full py-1.5" :disabled="b.id === active" @click="activate(b.id)">
          {{ b.id === active ? 'Active' : 'Use this broker' }}
        </button>
      </article>
    </div>

    <section v-if="isDefaultTenant" class="panel">
      <div class="panel-head">
        <div class="panel-title">Symbol specifications — {{ active }}</div>
        <span class="chip">จาก adapter · {{ specs[0]?.source || 'declared' }}</span>
      </div>
      <div class="overflow-x-auto">
        <table class="table-base">
          <thead>
            <tr>
              <th>Symbol</th><th>Digits</th><th>Point</th><th>Tick size</th><th>Contract</th>
              <th>Min / Max lot</th><th>Lot step</th><th>Stops level</th><th>Spread (typical)</th>
              <th>Commission / lot</th><th>Swap L/S</th><th>Source</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in specs" :key="s.symbol" class="hover:bg-ink-800/40">
              <td class="font-medium">{{ s.symbol }}</td>
              <td class="num">{{ s.digits }}</td>
              <td class="num">{{ s.point }}</td>
              <td class="num">{{ s.tick_size }}</td>
              <td class="num">{{ fmt(s.contract_size, 0) }}</td>
              <td class="num">{{ fmt(s.min_lot, 2) }} / {{ fmt(s.max_lot, 0) }}</td>
              <td class="num">{{ s.lot_step }}</td>
              <td class="num">{{ fmt(s.stops_level_points, 0) }}</td>
              <td class="num">{{ fmt(s.spread_typical_points, 0) }} pts</td>
              <td class="num">{{ money(s.commission_per_lot_round_turn) }}</td>
              <td class="num">{{ fmt(s.swap_long_per_lot, 2) }} / {{ fmt(s.swap_short_per_lot, 2) }}</td>
              <td><span class="chip" :class="s.source === 'broker' ? 'chip-up' : ''">{{ s.source }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
        ค่า digit / point / tick size / contract size / stops level ต้องอ่านจากบัญชีจริงเสมอ
        ตัวอย่าง: XAUUSD ที่ point 0.01 → 500 points = $5.00 แต่ถ้าโบรกเกอร์ใช้ point 0.001 จะเหลือ $0.50
      </p>
    </section>

    <div v-if="isDefaultTenant" class="grid gap-3 lg:grid-cols-2">
      <section class="panel">
        <div class="panel-head"><div class="panel-title">Connection & integrity</div></div>
        <dl class="px-4 py-3">
          <div class="kv"><dt>Health map</dt><dd>{{ JSON.stringify(healthMap) }}</dd></div>
          <div class="kv"><dt>Last reconcile</dt><dd>{{ reconcile?.ok === true ? 'matched' : reconcile?.ok === false ? 'mismatch' : 'not run' }}</dd></div>
          <div class="kv"><dt>Positions at broker</dt><dd>{{ reconcile?.positions ?? '—' }}</dd></div>
          <div class="kv"><dt>Missing at broker</dt><dd>{{ (reconcile?.missing_at_broker || []).join(', ') || '—' }}</dd></div>
          <div class="kv"><dt>Unknown locally</dt><dd>{{ (reconcile?.unknown_locally || []).join(', ') || '—' }}</dd></div>
          <div class="kv"><dt>Changed at broker</dt><dd>{{ (reconcile?.changed_at_broker || []).join(', ') || '—' }}</dd></div>
          <div v-if="reconcile?.reconciliation_required" class="mt-2 text-amber-300" role="alert">ต้องตรวจสอบบัญชีและประวัติ fill ก่อนดำเนินการต่อ ห้ามส่งคำสั่งซ้ำ</div>
        </dl>
        <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-muted">
          ระบบใช้ idempotency key ทุกคำสั่ง ตรวจสอบออร์เดอร์กับโบรกเกอร์หลังส่ง และหยุดรับคำสั่งเมื่อการเชื่อมต่อผิดปกติ
          ไม่ส่งซ้ำโดยพลการ
        </p>
      </section>
      <section class="panel">
        <div class="panel-head"><div class="panel-title">Broker profile specifications</div><span class="chip">YAML</span></div>
        <ol class="space-y-1.5 px-4 py-3 text-[10.5px] leading-relaxed text-slate-300">
          <li>1. profile ใน <span class="num text-gold-400">config/brokers.yaml</span> เก็บ adapter และ symbol specifications เท่านั้น</li>
          <li>2. แต่ละ broker login ถูกบันทึกเป็น managed account แยก Demo/Live และเข้ารหัสรายบัญชี</li>
          <li>3. Owner ควบคุมได้ก่อน assign; หลัง assign จะดู progress ได้อย่างเดียว</li>
          <li>4. Team manager ควบคุมได้ตาม assignment; สมาชิกอื่นอ่านสถานะได้ตามสิทธิ์</li>
        </ol>
        <p class="border-t border-ink-700/60 px-4 py-2 text-[10px] leading-relaxed text-amber-200/70">
          การบันทึกบัญชียังไม่เชื่อม MT5 หรือเปิด order execution; Demo validation/worker ยังอยู่ระหว่างพัฒนา และ Live ถูกปิดไว้
        </p>
      </section>
    </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../lib/api'
import { fmt, money } from '../lib/format'
import { state, toast } from '../lib/store'

const brokers = ref([])
const active = ref('')
const specs = ref([])
const loading = ref(false)
const managedAccounts = ref([])
const teams = ref([])
const assignmentDrafts = ref({})
const creatingAccount = ref(false)
const validatingAccountId = ref('')
const defaultTerminalPath = 'C:\\Program Files\\MetaTrader 5\\terminal64.exe'
const accountForm = ref({ provider: 'mt5', label: '', server: '', account_type: 'demo', login: '', password: '',
  terminal_path: defaultTerminalPath, validation_symbol: 'XAUUSD' })
const isPlatformSuperAdmin = computed(() => state.user?.platform_role === 'super_admin')
const isDefaultTenant = computed(() => state.user?.tenant_id === 'default')

const healthMap = computed(() => Object.fromEntries(brokers.value.map((b) => [b.id, b.health])))
const reconcile = computed(() => state.live?.reconcile || null)

async function load() {
  loading.value = true
  if (isPlatformSuperAdmin.value) {
    brokers.value = []
    active.value = ''
    specs.value = []
    managedAccounts.value = []
    teams.value = []
    loading.value = false
    return
  }
  try {
    if (isDefaultTenant.value) {
      const data = await api.get('/api/brokers')
      brokers.value = data.brokers || []
      active.value = data.active
      const sym = await api.get(`/api/brokers/${encodeURIComponent(active.value)}/symbols`)
      specs.value = sym.symbols || []
    } else {
      brokers.value = []
      active.value = ''
      specs.value = []
    }
    await loadManagedAccounts()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    loading.value = false
  }
}

async function loadManagedAccounts() {
  try {
    const [accountData, teamData] = await Promise.all([
      api.get('/api/broker-accounts'),
      api.get('/api/teams'),
    ])
    managedAccounts.value = accountData.accounts || []
    teams.value = teamData.teams || []
    assignmentDrafts.value = Object.fromEntries(managedAccounts.value.map((account) => [account.id, {
      team_id: account.assigned_team_id || '',
      manager_email: account.assigned_manager_email || '',
    }]))
  } catch (err) {
    toast(err.message, 'error')
  }
}

function teamManagers(teamId) {
  return teams.value.find((team) => team.id === teamId)?.members?.filter((member) => member.team_role === 'manager') || []
}

async function createManagedAccount() {
  if (creatingAccount.value) return
  creatingAccount.value = true
  try {
    await api.post('/api/broker-accounts', { ...accountForm.value })
    toast('เพิ่ม broker account record แล้ว (ยังไม่เชื่อม MT5)', 'success')
    accountForm.value = { provider: 'mt5', label: '', server: '', account_type: 'demo', login: '', password: '',
      terminal_path: defaultTerminalPath, validation_symbol: 'XAUUSD' }
    await loadManagedAccounts()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    accountForm.value.password = ''
    creatingAccount.value = false
  }
}

async function validateDemoAccount(account) {
  validatingAccountId.value = account.id
  try {
    const result = await api.post(`/api/broker-accounts/${encodeURIComponent(account.id)}/validate-demo`)
    toast(`Demo verified read-only: ${result.server} · ${result.symbol}; no order sent`, 'success')
    await loadManagedAccounts()
  } catch (err) {
    toast(err.message, 'error')
    await loadManagedAccounts()
  } finally {
    validatingAccountId.value = ''
  }
}

async function assignManagedAccount(account) {
  const assignment = assignmentDrafts.value[account.id]
  try {
                    await api.post(`/api/broker-accounts/${encodeURIComponent(account.id)}/assignment`, {
                      ...assignment,
                      expected_version: account.assignment_version,
                    })
    toast('มอบหมายบัญชีแล้ว; owner เปลี่ยนเป็น read-only', 'success')
    await loadManagedAccounts()
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function unassignManagedAccount(account) {
  try {
    await api.del(`/api/broker-accounts/${encodeURIComponent(account.id)}/assignment?expected_version=${account.assignment_version}`)
    toast('คืนสิทธิ์ควบคุมให้ owner แล้ว', 'success')
    await loadManagedAccounts()
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function activate(id) {
  try {
    await api.post(`/api/brokers/${encodeURIComponent(id)}/activate`)
    toast(`เปลี่ยนโบรกเกอร์เป็น ${id}`, 'success')
    await load()
  } catch (err) {
    toast(err.message, 'error')
  }
}

onMounted(load)
</script>
