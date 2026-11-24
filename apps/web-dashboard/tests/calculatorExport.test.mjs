import assert from 'node:assert/strict'
import test from 'node:test'

import { calculatorCsv, calculatorJson } from '../src/lib/calculatorExport.js'

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
