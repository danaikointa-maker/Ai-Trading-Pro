import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import { listenForInstall, registerWorker, watchForUpdates } from './lib/pwa'

createApp(App).use(router).mount('#app')

// beforeinstallprompt can fire before Vue has mounted, so listen from the start.
listenForInstall()

// Production only: in dev the Vite server serves modules on demand, and a cached
// shell would shadow hot updates. Registering late (after load) keeps the first
// paint off the critical path.
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    registerWorker().then((registration) => {
      if (registration) watchForUpdates()
    })
  })
}
