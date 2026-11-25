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

test('multiple rapid filter changes collapse to one fetch for the latest selection', async () => {
  const responses = []
  const requested = []
  const published = []
  let selection = { symbol: 'XAUUSD', timeframe: 'M1' }
  const queue = createLatestRefreshQueue({
    run: () => {
      requested.push({ ...selection })
      const response = deferred()
      responses.push(response)
      return response.promise
    },
    onResult: result => published.push(result),
  })

  const firstRequest = queue.refresh()
  selection = { symbol: 'XAUUSD', timeframe: 'M5' }
  const firstQueuedChange = queue.refresh({ invalidateIfBusy: true })
  selection = { symbol: 'XAUUSD', timeframe: 'H1' }
  const latestQueuedChange = queue.refresh({ invalidateIfBusy: true })
  assert.equal(responses.length, 1)

  responses[0].resolve({ ...requested[0] })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(responses.length, 2)
  assert.deepEqual(requested, [
    { symbol: 'XAUUSD', timeframe: 'M1' },
    { symbol: 'XAUUSD', timeframe: 'H1' },
  ])
  assert.deepEqual(published, [])

  responses[1].resolve({ ...requested[1] })
  await Promise.all([firstRequest, firstQueuedChange, latestQueuedChange])
  assert.deepEqual(published, [{ symbol: 'XAUUSD', timeframe: 'H1' }])
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
