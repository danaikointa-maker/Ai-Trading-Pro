const TIMEFRAME_SECONDS = Object.freeze({
  M1: 60,
  M5: 300,
  M15: 900,
  H1: 3600,
  H4: 14400,
})

function closedSnapshot(data) {
  const snapshot = data?.snapshot
  const quality = snapshot?.data_quality
  const timeframe = String(snapshot?.timeframe || '').toUpperCase()
  const timeframeSeconds = TIMEFRAME_SECONDS[timeframe]
  const barOpen = Number(snapshot?.server_time)
  const specSource = snapshot?.spec?.source

  if (quality?.ok !== true) {
    return { error: quality?.reason || 'ข้อมูลตลาดยังไม่สดหรือคุณภาพไม่ผ่าน', quality }
  }
  if (!timeframeSeconds || !Number.isFinite(barOpen) || barOpen <= 0
      || barOpen > 8.64e12 || !specSource) {
    return { error: 'ข้อมูลแท่งปิดหรือแหล่งสเปกไม่ครบ', quality }
  }

  return {
    snapshot,
    quality,
    timeframe,
    specSource,
    barOpenUtc: new Date(barOpen * 1000).toISOString(),
    barCloseUtc: new Date((barOpen + timeframeSeconds) * 1000).toISOString(),
  }
}

export function projectAtrVolatility(data) {
  const base = closedSnapshot(data)
  if (base.error) return { status: 'unavailable', reason: base.error, data_quality: base.quality }

  const price = Number(base.snapshot.price)
  const atr = Number(base.snapshot.indicators?.atr14)
  const atrPoints = Number(base.snapshot.indicators?.atr_points)
  if (base.snapshot.indicators?.atr14_valid !== true
      || ![price, atr, atrPoints].every(Number.isFinite) || price <= 0 || atr <= 0 || atrPoints <= 0) {
    return { status: 'unavailable', reason: 'ATR หรือราคาจากแท่งปิดไม่ถูกต้อง', data_quality: base.quality }
  }

  return {
    status: 'ready',
    symbol: base.snapshot.symbol,
    price,
    timeframe: base.timeframe,
    atr14: atr,
    atr_points: atrPoints,
    atr_percent: atr / price * 100,
    regime: base.snapshot.regime || null,
    quote_age_seconds: base.quality?.staleness_seconds ?? null,
    feed: base.quality?.feed || '—',
    spec_source: base.specSource,
    closed_bar_open_utc: base.barOpenUtc,
    closed_bar_close_utc: base.barCloseUtc,
    source: 'analysis_snapshot',
  }
}

function validZone(zone) {
  const low = Number(zone?.low)
  const high = Number(zone?.high)
  const mid = Number(zone?.mid)
  const distanceAtr = Number(zone?.distance_atr)
  const strength = Number(zone?.strength)
  return Boolean(zone?.id) && [low, high, mid, distanceAtr, strength].every(Number.isFinite)
    && low > 0 && low <= mid && mid <= high && distanceAtr >= 0
}

function zoneSummary(zone) {
  return {
    id: zone.id,
    low: Number(zone.low),
    high: Number(zone.high),
    mid: Number(zone.mid),
    quality: zone.quality,
    status: zone.status,
    strength: Number(zone.strength),
    distance_atr: Number(zone.distance_atr),
    families: Array.isArray(zone.families) ? zone.families : [],
  }
}

export function projectSupportResistance(data) {
  const base = closedSnapshot(data)
  if (base.error) return { status: 'unavailable', reason: base.error, data_quality: base.quality }

  const price = Number(base.snapshot.price)
  if (!Number.isFinite(price) || price <= 0) {
    return { status: 'unavailable', reason: 'ราคาจากข้อมูลวิเคราะห์ไม่ถูกต้อง', data_quality: base.quality }
  }

  const nearest = (zones) => (Array.isArray(zones) ? zones.filter(validZone) : [])
    .sort((a, b) => Number(a.distance_atr) - Number(b.distance_atr))
    .slice(0, 3).map(zoneSummary)

  return {
    status: 'ready',
    symbol: base.snapshot.symbol,
    price,
    timeframe: base.timeframe,
    supports: nearest(data?.supports),
    resistances: nearest(data?.resistances),
    quote_age_seconds: base.quality?.staleness_seconds ?? null,
    feed: base.quality?.feed || '—',
    spec_source: base.specSource,
    closed_bar_open_utc: base.barOpenUtc,
    closed_bar_close_utc: base.barCloseUtc,
    source: 'analysis_snapshot',
  }
}
