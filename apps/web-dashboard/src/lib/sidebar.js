import { computed, ref, watch } from 'vue'

const KEY = 'no7.sidebar.expanded.v1'
let expanded = true
let mobileOpen = false
try { expanded = localStorage.getItem(KEY) !== 'false' } catch { /* private storage */ }
try { mobileOpen = localStorage.getItem('no7.sidebar.mobile-open.v1') === 'true' } catch { /* private storage */ }
export const sidebarExpanded = ref(expanded)
export const mobileSidebarOpen = ref(mobileOpen)
export const desktopSidebar = ref(typeof window === 'undefined' || !window.matchMedia
  ? true : window.matchMedia('(min-width: 1024px)').matches)
export const sidebarOpen = computed(() => desktopSidebar.value ? sidebarExpanded.value : mobileSidebarOpen.value)
export const sidebarTarget = computed(() => desktopSidebar.value ? 'app-sidebar' : 'mobile-sidebar')

watch(sidebarExpanded, value => {
  try { localStorage.setItem(KEY, String(value)) } catch { /* toggle still works */ }
}, { flush: 'sync' })
watch(mobileSidebarOpen, value => {
  try { localStorage.setItem('no7.sidebar.mobile-open.v1', String(value)) } catch { /* memory only */ }
}, { flush: 'sync' })

export function toggleSidebar() {
  if (desktopSidebar.value) sidebarExpanded.value = !sidebarExpanded.value
  else mobileSidebarOpen.value = !mobileSidebarOpen.value
}
export function closeMobileSidebar() { mobileSidebarOpen.value = false }
export function syncSidebarBreakpoint() {
  if (!window.matchMedia) return () => {}
  const query = window.matchMedia('(min-width: 1024px)')
  const update = () => {
    desktopSidebar.value = query.matches
    if (query.matches) closeMobileSidebar()
  }
  update()
  query.addEventListener('change', update)
  return () => query.removeEventListener('change', update)
}
