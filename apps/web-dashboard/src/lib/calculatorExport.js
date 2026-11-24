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

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

export function calculatorPrintDocument(payload, { generatedAt = new Date().toISOString() } = {}) {
  const safePayload = payload && typeof payload === 'object' ? payload : {}
  const title = String(safePayload.tool || 'calculator').replaceAll('_', ' ')
  const details = JSON.stringify(safePayload, null, 2) || '{}'
  return `<!doctype html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>No7 Calculator · ${escapeHtml(title)}</title>
  <style>
    @page { margin: 16mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #17202a; background: #fff; font: 12pt/1.5 Arial, sans-serif; }
    main { max-width: 900px; margin: 0 auto; }
    .brand { color: #8a5a00; font-size: 10pt; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 4mm 0 1mm; font-size: 20pt; text-transform: capitalize; }
    .timestamp { color: #52606d; font-size: 9pt; }
    .notice { margin: 7mm 0; padding: 3mm; border: 1px solid #d8b565; background: #fff8e6; font-size: 10pt; }
    h2 { margin: 6mm 0 2mm; font-size: 12pt; }
    pre { margin: 0; padding: 4mm; border: 1px solid #d9dee5; border-radius: 2mm; white-space: pre-wrap; overflow-wrap: anywhere; font: 9pt/1.45 Consolas, monospace; }
    footer { margin-top: 8mm; border-top: 1px solid #d9dee5; padding-top: 2mm; color: #52606d; font-size: 8pt; }
  </style>
</head>
<body>
  <main>
    <div class="brand">No7 AI Trading Pro · Calculator</div>
    <h1>${escapeHtml(title)}</h1>
    <div class="timestamp">Exported: ${escapeHtml(generatedAt)}</div>
    <div class="notice">ผลลัพธ์นี้ใช้สำหรับคำนวณ วิเคราะห์ หรือทบทวนเท่านั้น ไม่ใช่คำสั่งเทรด การอนุมัติจาก Risk Engine หรือการรับประกันผลลัพธ์</div>
    <h2>Calculation data</h2>
    <pre>${escapeHtml(details)}</pre>
    <footer>พิมพ์หน้านี้หรือเลือก “Save as PDF” ในหน้าต่างพิมพ์ของเบราว์เซอร์ ข้อมูลที่แสดงมาจากผลลัพธ์ที่เลือกส่งออก</footer>
  </main>
</body>
</html>`
}
