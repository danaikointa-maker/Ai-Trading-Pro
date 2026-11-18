export const ZOOM_LEVELS = [2, 3, 4, 6, 8, 12, 16, 24, 32, 48]

export function nextBarSpacing(current, direction) {
  return direction > 0
    ? ZOOM_LEVELS.find(value => value > current + 0.01) ?? ZOOM_LEVELS.at(-1)
    : [...ZOOM_LEVELS].reverse().find(value => value < current - 0.01) ?? ZOOM_LEVELS[0]
}

export function latestLogicalRange(count, visibleBars, rightGap = 0) {
  if (count < 1) return null
  const width = Math.max(2, visibleBars)
  const to = count - 1 + Math.max(0, rightGap)
  return { from: to - width, to }
}

export function validPriceRange(min, max) {
  if (String(min).trim() === '' || String(max).trim() === '') return null
  const low = Number(min), high = Number(max)
  return Number.isFinite(low) && Number.isFinite(high) && high > low
    ? { minValue: low, maxValue: high } : null
}
