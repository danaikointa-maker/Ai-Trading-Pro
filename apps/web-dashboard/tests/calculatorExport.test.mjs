import assert from 'node:assert/strict'
import test from 'node:test'

import { calculatorCsv, calculatorJson, calculatorPrintDocument } from '../src/lib/calculatorExport.js'

test('calculator exports preserve nested evidence and quote CSV delimiters', () => {
  const payload = { tool: 'scenario', result: { median: 123.45, note: 'a,b"c' } }
  assert.deepEqual(JSON.parse(calculatorJson(payload)), payload)
  const csv = calculatorCsv(payload)
  assert.match(csv, /"tool","scenario"/)
  const escapedResult = JSON.stringify(payload.result).replaceAll('"', '""')
  assert.ok(csv.includes(`"result","${escapedResult}"`))
})

test('CSV export neutralizes formula-like text while keeping numeric negatives numeric', () => {
  const csv = calculatorCsv({ reason: '=HYPERLINK("https://example.invalid")', pnl: -4.5 })
  assert.match(csv, /"'=HYPERLINK\(""https:\/\/example\.invalid""\)"/)
  assert.match(csv, /"pnl","-4\.5"/)
})

test('print-to-PDF document safely escapes untrusted calculator text', () => {
  const html = calculatorPrintDocument({
    tool: 'risk_reward',
    result: { note: '</pre><script>alert(1)</script><img src=x onerror=alert(2)>' },
  }, { generatedAt: '2026-11-24T12:00:00Z' })

  assert.match(html, /risk reward/)
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  assert.match(html, /&lt;img src=x onerror=alert\(2\)&gt;/)
  assert.doesNotMatch(html, /<script|<img/)
  assert.match(html, /ไม่ใช่คำสั่งเทรด/)
  assert.match(html, /Save as PDF/)
})
