import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backend = process.env.NO7_BACKEND || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: false,
    allowedHosts: true,
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/ws': { target: backend, ws: true, changeOrigin: true },
    },
  },
  preview: { host: '0.0.0.0', allowedHosts: true },
  build: {
    outDir: 'dist',
    // No more blanket 1600 kB allowance: split the libraries so a change to app
    // code does not force a 1 MB re-download, and so the warning stays honest.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('lightweight-charts')) return 'chart'
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (id.includes('vue-router')) return 'vue-router'
          if (id.includes('/vue/') || id.includes('@vue')) return 'vue'
          return 'vendor'
        },
      },
    },
  },
})
