export function createLatestRefreshQueue({ run, onStart, onResult, onError }) {
  let generation = 0
  let inFlight = null
  let queued = false
  let closed = false

  async function execute(requestGeneration) {
    try {
      onStart?.()
      const result = await run()
      if (!closed && requestGeneration === generation) onResult?.(result)
    } catch (error) {
      if (!closed && requestGeneration === generation) onError?.(error)
    } finally {
      inFlight = null
      if (queued && !closed) {
        queued = false
        return refresh()
      }
    }
  }

  function refresh({ invalidateIfBusy = false } = {}) {
    if (closed) return Promise.resolve()
    if (inFlight) {
      if (invalidateIfBusy) generation += 1
      queued = true
      return inFlight
    }

    generation += 1
    inFlight = execute(generation)
    return inFlight
  }

  function close() {
    closed = true
    generation += 1
    queued = false
  }

  return { refresh, close }
}
