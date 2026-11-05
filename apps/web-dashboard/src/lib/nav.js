// Single source of truth for the navigation (used by the desktop sidebar and the
// mobile bottom bar so the two can never drift apart).

const icon = (path) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
  stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4">${path}</svg>`

export const nav = [
  { to: '/', label: 'Terminal', short: 'เทอร์มินัล', badge: 'live', icon: icon('<path d="M3 17l5-6 4 3 5-7 4 4"/><path d="M3 21h18"/>') },
  { to: '/forecast', label: 'AI Forecast', short: 'พยากรณ์', icon: icon('<path d="M4 19V5"/><path d="M4 15c3 0 4-8 8-8s5 6 8 6"/><path d="M16 19h4"/>') },
  { to: '/zones', label: 'Zones S/R', short: 'โซน', icon: icon('<path d="M4 7h16M4 12h16M4 17h16"/>') },
  { to: '/trades', label: 'Trades', short: 'เทรด', icon: icon('<path d="M4 6h16v12H4z"/><path d="M8 10h8M8 14h5"/>') },
  { to: '/risk', label: 'Risk Engine', short: 'ความเสี่ยง', icon: icon('<path d="M12 3l8 4v6c0 5-4 7-8 8-4-1-8-3-8-8V7z"/><path d="M9 12l2 2 4-4"/>') },
  { to: '/backtest', label: 'Backtest Lab', short: 'ทดสอบย้อนหลัง', icon: icon('<path d="M4 20V8m5 12V4m5 16v-7m5 7V9"/>') },
  { to: '/journal', label: 'AI Journal', short: 'บันทึก', icon: icon('<path d="M6 3h9l3 3v15H6z"/><path d="M9 9h6M9 13h6M9 17h4"/>') },
  { to: '/brokers', label: 'Brokers', short: 'โบรกเกอร์', icon: icon('<path d="M3 10h18M5 10V6l7-3 7 3v4"/><path d="M5 10v9h14v-9"/>') },
  { to: '/system', label: 'System', short: 'ระบบ', icon: icon('<circle cx="12" cy="12" r="3"/><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6l2.1 2.1m0-12.8l-2.1 2.1M7.7 16.3l-2.1 2.1"/>') },
]

// The four screens that get a permanent seat in the mobile bottom bar.
export const primaryNav = nav.filter((item) => ['/', '/forecast', '/zones', '/trades'].includes(item.to))
