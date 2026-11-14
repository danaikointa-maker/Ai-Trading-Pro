import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const server = await createServer({
  root,
  optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true, hmr: false },
  appType: 'custom',
})

try {
  const { code } = await server.transformRequest('/src/views/Trades.vue')
  assert.ok(code.includes('selectTrade'), 'trade review selection handler is compiled')
  assert.ok(code.includes('onClick'), 'trade rows compile a click handler')
  assert.ok(code.includes('onKeydown'), 'trade rows compile keyboard handlers')
  assert.ok(code.includes('enter') && code.includes('space'), 'Enter and Space modifiers are compiled')
  assert.ok(code.includes('aria-expanded'), 'selected state has an accessible expanded-state attribute')
  console.log('Trades review SFC transform and click/keyboard handler assertions passed')
} finally {
  await server.close()
}