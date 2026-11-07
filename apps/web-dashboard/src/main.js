import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'

createApp(App).use(router).mount('#app')

// Production only: in dev the Vite server serves modules on demand, and a cached
// shell would shadow hot updates. Registering late (after load) keeps the first
// paint off the critical path.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch((err) => {
      console.warn('service worker not registered:', err)
    })
  })
}
