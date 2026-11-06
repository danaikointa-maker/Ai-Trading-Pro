import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './lib/api'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true, title: 'Sign in' } },
  { path: '/', name: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { title: 'Trading Terminal' } },
  { path: '/forecast', name: 'forecast', component: () => import('./views/Forecast.vue'), meta: { title: 'AI Forecast' } },
  { path: '/zones', name: 'zones', component: () => import('./views/Zones.vue'), meta: { title: 'Support & Resistance' } },
  { path: '/trades', name: 'trades', component: () => import('./views/Trades.vue'), meta: { title: 'Trades & Performance' } },
  { path: '/risk', name: 'risk', component: () => import('./views/Risk.vue'), meta: { title: 'Risk Engine' } },
  { path: '/backtest', name: 'backtest', component: () => import('./views/Backtest.vue'), meta: { title: 'Backtest Lab' } },
  { path: '/journal', name: 'journal', component: () => import('./views/Journal.vue'), meta: { title: 'AI Journal' } },
  { path: '/brokers', name: 'brokers', component: () => import('./views/Brokers.vue'), meta: { title: 'Brokers' } },
  { path: '/system', name: 'system', component: () => import('./views/System.vue'), meta: { title: 'System' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

// A deploy changes the hashed chunk names. If the browser is still holding an
// older index.html, the dynamic import of a view 404s and the navigation is
// aborted — the user stays on the login page with a valid token. Recover with a
// single full reload (which fetches the fresh shell) instead of freezing.
const CHUNK_RELOAD_KEY = 'no7.chunk-reload-at'
router.onError((error, to) => {
  const message = String(error && error.message ? error.message : error)
  const looksLikeChunk = /dynamically imported module|Importing a module script failed|Failed to fetch|error loading/i.test(message)
  if (!looksLikeChunk) return
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || 0)
  if (Date.now() - last < 10000) return // never loop
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  window.location.assign((to && to.fullPath) || '/')
})

router.beforeEach((to) => {
  document.title = `${to.meta.title || 'No7'} · No7 AI Trading Pro`
  if (!to.meta.public && !getToken()) return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && getToken()) return { name: 'dashboard' }
  return true
})

export default router
