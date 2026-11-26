function exportValue(value) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function printableValue(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
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

export function calculatorPrintHtml(payload, generatedAt = new Date()) {
  const data = payload && typeof payload === 'object' && !Array.isArray(payload) ? payload : {}
  const tool = typeof data.tool === 'string' ? data.tool : 'calculator'
  const symbol = typeof data.symbol === 'string' ? data.symbol : ''
  const title = ['No7 AI Trading Pro', tool, symbol].filter(Boolean).join(' · ')
  const timestamp = generatedAt instanceof Date && Number.isFinite(generatedAt.getTime())
    ? generatedAt.toISOString()
    : new Date().toISOString()
  const rows = Object.entries(data).map(([key, value]) =>
    '<tr><th scope="row">' + escapeHtml(key) + '</th><td><pre>' +
    escapeHtml(printableValue(value)) + '</pre></td></tr>',
  ).join('')

  return [
    '<!doctype html><html lang="th"><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    '<title>' + escapeHtml(title) + '</title>',
    '<style>',
    '@page{size:A4;margin:14mm}*{box-sizing:border-box}',
    'body{margin:0;color:#17212b;background:#fff;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}',
    'header{border-bottom:2px solid #c18a19;padding:0 0 12px;margin-bottom:16px}',
    'h1{font-size:20px;margin:0 0 4px}p{margin:4px 0;color:#52606d}',
    'table{width:100%;border-collapse:collapse;table-layout:fixed}',
    'th,td{border:1px solid #ccd3da;padding:8px;text-align:left;vertical-align:top}',
    'th{width:24%;background:#f1f4f7;font-weight:600;overflow-wrap:anywhere}',
    'pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}',
    '.notice{margin-top:16px;padding:10px;border:1px solid #d6c28e;background:#fffaf0;color:#51421c}',
    '@media print{tr{break-inside:avoid}thead{display:table-header-group}}',
    '</style></head><body><header><h1>' + escapeHtml(title) + '</h1>',
    '<p>เวลาสร้างรายงาน (UTC): ' + escapeHtml(timestamp) + '</p></header>',
    '<table><tbody>' + rows + '</tbody></table>',
    '<p class="notice">ข้อมูลนี้เป็นผลคำนวณหรือข้อมูลอ่านอย่างเดียวสำหรับประกอบการศึกษา ' +
      'ไม่ใช่คำสั่งซื้อขายหรือการรับรองผลตอบแทน</p>',
    '</body></html>',
  ].join('')
}

export function openCalculatorPdf(payload, windowRef = globalThis.window, generatedAt = new Date()) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)
      || !windowRef || typeof windowRef.open !== 'function') return false

  const printWindow = windowRef.open('', '_blank')
  if (!printWindow || !printWindow.document || typeof printWindow.print !== 'function') {
    printWindow?.close?.()
    return false
  }

  try {
    printWindow.onafterprint = () => printWindow.close?.()
    printWindow.document.open()
    printWindow.document.write(calculatorPrintHtml(payload, generatedAt))
    printWindow.document.close()
    printWindow.focus?.()
    printWindow.print()
    return true
  } catch {
    printWindow.close?.()
    return false
  }
}

export function calculatorCsv(payload) {
  const rows = [['field', 'value']]
  for (const [key, value] of Object.entries(payload || {})) {
    rows.push([key, value])
  }
  return rows.map((row) => row.map(quoteCsv).join(',')).join('\r\n')
}
