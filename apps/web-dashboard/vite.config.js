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
  build: { outDir: 'dist', chunkSizeWarningLimit: 1600 },
})
