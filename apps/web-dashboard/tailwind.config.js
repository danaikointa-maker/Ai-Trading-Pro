/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#07090c', 900: '#0a0d12', 850: '#0d1117', 800: '#111823', 700: '#1a2331', 600: '#26333f' },
        gold: { 400: '#f5b541', 500: '#e09b1f', 600: '#b97c12' },
        up: '#34d399',
        down: '#f87171',
        muted: '#8b98a9',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: { panel: '0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 24px -20px rgba(0,0,0,0.9)' },
    },
  },
  plugins: [],
}
