// Drop overlapping timer ticks instead of queuing requests behind a slow API.
export function singleFlight(task) {
  let running = false
  return async (...args) => {
    if (running) return
    running = true
    try { return await task(...args) } finally { running = false }
  }
}
