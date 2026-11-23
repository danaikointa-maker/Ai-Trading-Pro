export const ZOOM_LEVELS = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48]

export function clampBarSpacing(value) {
  const spacing = Number(value)
  return Number.isFinite(spacing) ? Math.min(48, Math.max(2, spacing)) : 16
}

export function nextBarSpacing(current, direction) {
  const spacing = clampBarSpacing(current)
  return direction > 0
    ? ZOOM_LEVELS.find(value => value > spacing + 0.01) ?? ZOOM_LEVELS.at(-1)
    : [...ZOOM_LEVELS].reverse().find(value => value < spacing - 0.01) ?? ZOOM_LEVELS[0]
}

export function latestLogicalRange(count, visibleBars, rightGap = 0) {
  if (!Number.isFinite(count) || count < 1) return null
  const width = Math.max(2, Number(visibleBars) || 2)
  const gap = Math.max(0, Number(rightGap) || 0)
  const to = count - 1 + gap
  return { from: to - width, to }
}

export function validPriceRange(min, max) {
  if (String(min).trim() === '' || String(max).trim() === '') return null
  const low = Number(min), high = Number(max)
  return Number.isFinite(low) && Number.isFinite(high) && high > low
    ? { minValue: low, maxValue: high } : null
}

export function validTimeRange(range, first, last) {
  const from = Number(range?.from), to = Number(range?.to)
  return Number.isFinite(from) && Number.isFinite(to) && to > from
    && Number.isFinite(first) && Number.isFinite(last) && from >= first && to <= last
}

export function matchesChartSymbol(candidate, requested) {
  const source = String(candidate || '').trim().toUpperCase()
  const target = String(requested || '').trim().toUpperCase()
  return Boolean(target && (source === target || source.startsWith(`${target}.`)))
}

export function shortMarkerSpan(width, rightInset = 78, length = 132) {
  if (!Number.isFinite(width) || width < 1) return null
  const right = Math.max(0, width - Math.max(0, rightInset))
  const left = Math.max(0, right - Math.max(8, length))
  return right - left >= 8 ? { left, right } : null
}
