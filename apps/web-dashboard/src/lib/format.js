export const fmt = (v, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
export const money = (v, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n < 0 ? '-' : ''}$${fmt(Math.abs(n), digits)}`
}
export const signed = (v, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${fmt(n, digits)}`
}
export const pct = (v, digits = 0) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}
export const pts = (v) => {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return `${Number(v) > 0 ? '+' : ''}${fmt(v, 0)} pts`
}
export const clock = (ts) => {
  if (!ts) return '—'
  const d = new Date(Number(ts) * 1000)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
export const datetime = (ts) => {
  if (!ts) return '—'
  const d = new Date(Number(ts) * 1000)
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}
export const relative = (ts) => {
  if (!ts) return '—'
  const diff = Number(ts) * 1000 - Date.now()
  const abs = Math.abs(diff) / 1000
  const suffix = diff > 0 ? '' : ' ago'
  if (abs < 60) return `${Math.round(abs)}s${suffix}`
  if (abs < 3600) return `${Math.round(abs / 60)}m${suffix}`
  return `${Math.round(abs / 3600)}h${suffix}`
}
export const cls = (...parts) => parts.filter(Boolean).join(' ')

export const actionTone = (action) => {
  if (action === 'BUY') return 'text-up'
  if (action === 'SELL') return 'text-down'
  if (action === 'WAIT') return 'text-amber-300'
  return 'text-muted'
}
export const qualityTone = (q) => (q === 'high' ? 'chip-up' : q === 'medium' ? 'chip-gold' : 'chip')
export const directionTone = (d) =>
  d === 'up' || d === 'trending_up' ? 'text-up' : d === 'down' || d === 'trending_down' ? 'text-down' : 'text-muted'
