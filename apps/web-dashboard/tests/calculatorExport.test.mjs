import assert from 'node:assert/strict'
import test from 'node:test'

import { calculatorCsv, calculatorJson, calculatorPrintHtml, openCalculatorPdf } from '../src/lib/calculatorExport.js'

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

test('print report includes UTF-8 data, provenance and a clear advisory disclaimer', () => {
  const html = calculatorPrintHtml({
    tool: 'scenario', symbol: 'XAUUSD', source: { mode: 'simulate' }, result: { median: 123.45 },
  }, new Date('2026-11-26T00:00:00.000Z'))

  assert.match(html, /<meta charset="utf-8">/)
  assert.match(html, /No7 AI Trading Pro · scenario · XAUUSD/)
  assert.match(html, /2026-11-26T00:00:00\.000Z/)
  assert.match(html, /&quot;mode&quot;: &quot;simulate&quot;/)
  assert.match(html, /ไม่ใช่คำสั่งซื้อขาย/)
  assert.match(html, /@page\{size:A4/)
})

test('print report escapes user-controlled values and contains no injected markup', () => {
  const html = calculatorPrintHtml({
    tool: '<script>alert(1)</script>', symbol: 'ทอง & XAU',
    note: '</pre><img src=x onerror=alert(1)>',
  }, new Date('2026-11-26T00:00:00.000Z'))

  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
  assert.match(html, /ทอง &amp; XAU/)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(html, /<script>|<img\b/i)
})

test('PDF action opens a printable report; popup blocking is reported without fallback side effects', () => {
  let html = ''
  let printed = 0
  let closed = 0
  const printWindow = {
    document: { open() {}, write(value) { html = value }, close() {} },
    focus() {},
    print() { printed += 1 },
    close() { closed += 1 },
    onafterprint: null,
  }
  const windowRef = { open() { return printWindow } }

  assert.equal(openCalculatorPdf({ tool: 'points' }, windowRef), true)
  assert.equal(printed, 1)
  assert.match(html, /No7 AI Trading Pro · points/)
  assert.equal(typeof printWindow.onafterprint, 'function')
  printWindow.onafterprint()
  assert.equal(closed, 1)
  assert.equal(openCalculatorPdf({ tool: 'points' }, { open() { return null } }), false)
  assert.equal(openCalculatorPdf(null, windowRef), false)
})
