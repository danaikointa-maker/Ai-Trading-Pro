export function lotPrecision(step) {
  const value = Number(step)
  if (!Number.isFinite(value) || value <= 0) return 2
  for (let digits = 0; digits <= 8; digits += 1) {
    const scaled = value * (10 ** digits)
    if (Math.abs(scaled - Math.round(scaled)) < 1e-9) return digits
  }
  return 8
}
