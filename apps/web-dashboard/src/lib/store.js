import { computed, reactive } from 'vue'
import { api, getToken, setToken } from './api'

export const state = reactive({
  token: getToken(),
  user: null,
  live: null,
  trading: null,
  config: null,
  brokers: null,
  symbol: localStorage.getItem('no7.symbol') || 'XAUUSD',
  timeframe: localStorage.getItem('no7.tf') || 'M5',
  range: Number(localStorage.getItem('no7.range') || 240),
  connected: false,
  transport: 'idle',
  toasts: [],
  loading: false,
  lastError: '',
  serverUnreachable: false,   // shell served, API not answering — say so, do not pretend
  lastLiveAt: 0,              // epoch ms of the newest data actually received
  positionReceivedAt: 0,
  positionNow: Date.now(),
  riskSettings: null,
})

let socket = null
let pollTimer = null
let positionTimer = null
let retry = 0

export const signal = computed(() => state.live?.signal || null)
export const analysis = computed(() => state.live?.analysis || null)
export const forecast = computed(() => state.live?.forecast || null)
export const riskState = computed(() => state.live?.risk_state || null)
export const positionsAvailable = computed(() => {
  const status = state.live?.positions_status
  const elapsed = (state.positionNow - state.positionReceivedAt) / 1000
  return !state.serverUnreachable && status?.available === true
    && Array.isArray(state.live?.positions)
    && typeof status.age_seconds === 'number' && Number.isFinite(status.age_seconds)
    && status.age_seconds >= 0 && elapsed >= 0 && status.age_seconds + elapsed <= 10
})
export const positions = computed(() => positionsAvailable.value ? state.live.positions : [])
export const account = computed(() => state.live?.account || null)
export const mode = computed(() => state.live?.mode || 'manual')

// Mirror of the server's role rules (services/api_gateway/roles.py). The UI uses it
// to disable actions honestly; the server still decides, so a stale client cannot
// grant itself anything.
export const permissions = computed(() => {
  const role = state.user?.role || 'viewer'
  const rank = { viewer: 1, trader: 2, admin: 3 }[role] || 1
  return {
    role,
    canTrade: rank >= 2,
    canManageUsers: rank >= 3,
    reason: rank >= 2 ? '' : 'บัญชีนี้เป็น viewer — อ่านได้อย่างเดียว',
  }
})

export function toast(message, type = 'info', timeout = 4200) {
  const id = Math.random().toString(36).slice(2)
  state.toasts.push({ id, message, type })
  setTimeout(() => {
    const i = state.toasts.findIndex((t) => t.id === id)
    if (i >= 0) state.toasts.splice(i, 1)
  }, timeout)
}

export async function login(email, password) {
  const data = await api.post('/api/auth/login', { email, password })
  setToken(data.token)
  state.token = data.token
  state.user = data.user
  return data
}

export function logout() {
  setToken('')
  state.token = ''
  state.user = null
  stopLive()
}

export async function bootstrap() {
  if (!state.token) return
  const [me, config, brokers] = await Promise.all([
    api.get('/api/auth/me', { silent: true }).catch(() => null),
    api.get('/api/system/config', { silent: true }).catch(() => null),
    api.get('/api/brokers', { silent: true }).catch(() => null),
  ])
  if (me) state.user = me.user
  if (config) {
    state.config = config
    if (config.symbols && !config.symbols.includes(state.symbol)) state.symbol = config.symbols[0]
  }
  if (brokers) state.brokers = brokers
  await refreshTrading()
}

export async function refreshTrading() {
  const data = await api.get('/api/trading/state', { silent: true }).catch(() => null)
  if (data) state.trading = data
}

export function setSymbol(symbol) {
  state.symbol = symbol
  localStorage.setItem('no7.symbol', symbol)
  api.post('/api/system/symbol', { symbol }).catch(() => {})
}
export function setTimeframe(tf) {
  state.timeframe = tf
  localStorage.setItem('no7.tf', tf)
}

export function applyLive(payload, transport = 'ws') {
  // "tick" frames are intentionally light (no analysis/forecast). Merging instead
  // of replacing keeps those blocks on screen between full snapshots — replacing
  // used to blank every analysis panel one second after load.
  const previous = state.live || {}
  const merged = { ...previous, ...payload }
  // Unlike analysis, position authority must be supplied together in every frame.
  merged.positions_status = Array.isArray(payload.positions) && payload.positions_status
    ? payload.positions_status : { available: false }
  if (merged.analysis == null) merged.analysis = previous.analysis ?? null
  // Omitted forecast in a light frame may inherit; an explicit null revokes it.
  // Never carry a model opinion across symbol/version/approval changes.
  if (!Object.prototype.hasOwnProperty.call(payload, 'forecast')) {
    merged.forecast = previous.forecast ?? null
  }
  if (merged.forecast && (
    merged.forecast.symbol !== merged.symbol
    || (merged.model && merged.forecast.model_version !== merged.model.version)
    || (merged.forecast.model_approved && merged.model?.approved !== true)
  )) merged.forecast = null
  state.live = merged
  state.positionNow = Date.now()
  state.positionReceivedAt = state.positionNow
  if (payload.symbol && payload.symbol !== state.symbol) state.symbol = payload.symbol
  state.connected = true
  state.serverUnreachable = false
  state.lastLiveAt = Date.now()
  state.transport = transport
}

export function startLive() {
  stopLive()
  if (!state.token) return
  connectSocket()
  positionTimer = setInterval(() => { state.positionNow = Date.now() }, 250)
  pollTimer = setInterval(async () => {
    if (!state.token) return
    if (state.transport !== 'ws') {
      const data = await api.get('/api/trading/live', { silent: true }).catch(() => null)
      if (data) applyLive(data, 'polling')
    } else {
      await refreshTrading()
    }
  }, 5000)
}

function connectSocket() {
  try {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/ws/live?token=${encodeURIComponent(state.token)}`)
    socket.onopen = () => {
      retry = 0
      state.transport = 'ws'
    }
    socket.onmessage = (event) => {
      try {
        applyLive(JSON.parse(event.data))
      } catch {
        /* ignore malformed frame */
      }
    }
    socket.onclose = () => {
      state.connected = false
      state.transport = 'polling'
      socket = null
      retry += 1
      if (state.token) setTimeout(connectSocket, Math.min(15000, 1200 * retry))
    }
    socket.onerror = () => {
      state.transport = 'polling'
    }
  } catch {
    state.transport = 'polling'
  }
}

export function stopLive() {
  if (socket) {
    socket.onclose = null
    socket.close()
    socket = null
  }
  if (pollTimer) clearInterval(pollTimer)
  if (positionTimer) clearInterval(positionTimer)
  positionTimer = null
  pollTimer = null
  if (state.live) state.live.positions_status = { available: false }
  state.connected = false
}

// The API tells us when it cannot be reached. A websocket that drops only means the
// socket is gone (we fall back to polling), so only an HTTP failure flips this flag.
window.addEventListener('no7:server-unreachable', () => { state.serverUnreachable = true })
window.addEventListener('no7:server-reachable', () => { state.serverUnreachable = false })

window.addEventListener('no7:unauthorized', () => {
  state.user = null
  stopLive()
})
