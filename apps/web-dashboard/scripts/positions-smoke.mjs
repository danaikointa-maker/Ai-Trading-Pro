import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { readFileSync } from 'node:fs'

// Compile the actual SFC/store without listening on a port or contacting an API.
globalThis.localStorage = { getItem: () => null }
globalThis.window = new EventTarget()
const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
try {
  const { closeAllFeedback } = await server.ssrLoadModule('/src/lib/close-results.js')
  const { closeFeedback } = await server.ssrLoadModule('/src/lib/close-results.js')
  const uncertain = closeFeedback({ ok: false, outcome: 'unknown', unknown: 1 })
  assert.match(uncertain.message, /ไม่ทราบผล/)
  assert.doesNotMatch(uncertain.message, /ปฏิเสธ/)
  for (const reply of [{ ok: true }, { ok: false }, {}, null, { ok: 'true' }]) {
    const feedback = closeFeedback(reply)
    assert.notEqual(feedback.type, 'success')
    assert.match(feedback.message, /ยังไม่ยืนยัน exposure/)
    assert.match(feedback.message, /ก่อนส่งซ้ำ/)
    assert.match(feedback.message, reply?.ok === true ? /ตอบรับ/ : reply?.ok === false ? /ปฏิเสธ/ : /ไม่ทราบผล/)
  }
  const tableSource = readFileSync(new URL('../src/components/PositionsTable.vue', import.meta.url), 'utf8')
  assert.match(tableSource, /closeFeedback\(res\)/)
  assert.match(tableSource, /closeFeedback\(err\.detail\)/)
  assert.doesNotMatch(tableSource, /ปิดไม้ .*แล้ว/)
  const partial = closeAllFeedback({ ok: false, attempted: 2, accepted: 1, rejected: 0,
    unknown: 1, not_attempted: 2, exposure_verified: false })
  assert.match(partial.message, /ไม่ทราบผล 1/)
  assert.match(partial.message, /ยังไม่ส่ง 2/)
  assert.equal(partial.type, 'error')
  for (const result of [{}, { ok: true, closed: [{ ok: false }] },
    { ok: false, attempted: 2, accepted: 1, rejected: 1, exposure_verified: false },
    { ok: true, attempted: 2, accepted: 2, rejected: 0, exposure_verified: false }]) {
    const feedback = closeAllFeedback(result)
    assert.notEqual(feedback.type, 'success')
    assert.match(feedback.message, /ยังไม่ยืนยัน exposure/)
    assert.doesNotMatch(feedback.message, /ปิด \d+ ไม้/)
  }
  const store = await server.ssrLoadModule('/src/lib/store.js')
  const { default: Table } = await server.ssrLoadModule('/src/components/PositionsTable.vue')
  const html = () => renderToString(createSSRApp(Table))
  const owned = (rows = []) => ({ positions: rows, positions_status: { available: true, age_seconds: 1 } })
  const row = { ticket: 'fixture-position', direction: 'up', symbol: 'XAUUSD', volume: 0.1 }
  store.state.user = { role: 'trader' }

  for (const payload of [null, {}, { positions: [] }, { positions: [], positions_status: { available: false } }]) {
    store.state.live = null
    if (payload) store.applyLive(payload)
    assert.equal(store.positionsAvailable?.value, false, 'missing/unavailable evidence is unknown')
    const output = await html()
    assert.match(output, /ยืนยันสถานะ positions ไม่ได้/)
    assert.doesNotMatch(output, /ยังไม่มีไม้ที่เปิดอยู่|0 ไม้/)
    assert.match(output, /disabled[^>]*>Close all/)
  }

  store.applyLive(owned())
  assert.equal(store.positionsAvailable.value, true)
  assert.match(await html(), /ยังไม่มีไม้ที่เปิดอยู่/)
  store.applyLive(owned([row]))
  assert.equal(store.positions.value.length, 1)
  assert.match(await html(), /fixture-position/)
  assert.doesNotMatch(await html(), /disabled[^>]*>Close all/)
  store.state.user = { role: 'viewer' }
  assert.match(await html(), /disabled[^>]*>Close<\/button>/)
  store.state.user = { role: 'trader' }

  // Light/error frames must not inherit an earlier availability claim.
  store.applyLive({ type: 'tick', ticker: { last: 2000 } })
  assert.equal(store.positionsAvailable.value, false)
  assert.deepEqual(store.positions.value, [])
  assert.doesNotMatch(await html(), /fixture-position/)

  for (const age of [undefined, null, '1', -1, 11, NaN, Infinity]) {
    store.applyLive({ positions: [row], positions_status: { available: true, age_seconds: age } })
    assert.equal(store.positionsAvailable.value, false, `reject malformed/stale age ${age}`)
  }
  store.applyLive({ positions: {}, positions_status: { available: true, age_seconds: 0 } })
  assert.equal(store.positionsAvailable.value, false)

  store.applyLive(owned([row]))
  store.state.positionNow += 9001
  assert.equal(store.positionsAvailable.value, false, 'transport silence expires position evidence')
  assert.equal(store.state.live.positions.length, 1, 'do not erase prior evidence')
  store.applyLive(owned([row]))
  store.state.serverUnreachable = true
  assert.equal(store.positionsAvailable.value, false)
  store.state.serverUnreachable = false
  store.stopLive()
  assert.equal(store.positionsAvailable.value, false)
  console.log('positions: unknown, owned empty, stale and unavailable states all behave')
} finally {
  await server.close()
}