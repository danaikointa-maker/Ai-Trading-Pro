import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/PointsCalculator.vue', import.meta.url), 'utf8')
assert.match(source, /Gross profit/)
assert.match(source, /Commission · round turn/)
assert.match(source, /Net estimate · after commission/)
assert.match(source, /Spread cost @ typical/)
assert.match(source, /Spread cost แสดงแยกและยังไม่หักจาก Net/)
assert.match(source, /Runtime market spec/)
assert.match(source, /ยังไม่ผูกกับบัญชี MT5 ที่เลือก/)
assert.match(source, /api\.get\(`\/api\/market\/calculator/)
assert.doesNotMatch(source, /api\.post\(/)
assert.doesNotMatch(source, /\/api\/trading\/(order|close)/)
console.log('calculator: cost breakdown is labeled; runtime spec and read-only scope are explicit')
