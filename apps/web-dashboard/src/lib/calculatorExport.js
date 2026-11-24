function exportValue(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function quoteCsv(value) {
  const text = exportValue(value)
  const protectedText = typeof value === 'string' && /^[\u0000-\u0020]*[=+@-]/.test(text)
    ? `'${text}`
    : text
  return `"${protectedText.replaceAll('"', '""')}"`
}

export function calculatorJson(payload) {
  return JSON.stringify(payload, null, 2)
}

export function calculatorCsv(payload) {
  const rows = [['field', 'value']]
  for (const [key, value] of Object.entries(payload || {})) {
    rows.push([key, value])
  }
  return rows.map((row) => row.map(quoteCsv).join(',')).join('\r\n')
}
