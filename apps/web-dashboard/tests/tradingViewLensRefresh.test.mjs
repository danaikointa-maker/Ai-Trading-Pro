import test from 'node:test'
import assert from 'node:assert/strict'

import { createLatestRefreshQueue } from '../src/lib/latestRefreshQueue.js'

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('a queued filter change discards old evidence and fetches the current selection', async () => {
  const responses = []
  const published = []
  const queue = createLatestRefreshQueue({
    run: () => {
      const response = deferred()
      responses.push(response)
      return response.promise
    },
    onResult: result => published.push(result),
  })

  const firstRequest = queue.refresh()
  const changedSelection = queue.refresh({ invalidateIfBusy: true })
  assert.equal(responses.length, 1)

  responses[0].resolve({ symbol: 'XAUUSD', timeframe: 'M1' })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(responses.length, 2)
  assert.deepEqual(published, [])

  responses[1].resolve({ symbol: 'XAUUSD', timeframe: 'M5' })
  await Promise.all([firstRequest, changedSelection])
  assert.deepEqual(published, [{ symbol: 'XAUUSD', timeframe: 'M5' }])
})

test('closing the panel prevents pending evidence from publishing', async () => {
  const response = deferred()
  const published = []
  const queue = createLatestRefreshQueue({
    run: () => response.promise,
    onResult: result => published.push(result),
  })
  const pendingRequest = queue.refresh()

  queue.close()
  response.resolve({ symbol: 'XAUUSD', timeframe: 'M1' })
  await pendingRequest

  assert.deepEqual(published, [])
  await queue.refresh()
  assert.deepEqual(published, [])
})
