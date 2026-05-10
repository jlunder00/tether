import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { VOICE } from './composables/useTheme'
import './assets/themes.css'
import './assets/motifs.css'
import './assets/theme-distinctives.css'
import './assets/detail-panel.css'
import './style.css'

// Boot: apply saved theme + mode before Vue mounts (prevents flash)
const savedTheme = localStorage.getItem('tether-theme') ?? 'tether'
const savedMode = localStorage.getItem('tether-mode') ?? (new Date().getHours() >= 7 && new Date().getHours() < 19 ? 'light' : 'dark')
document.documentElement.dataset.theme = savedTheme
document.documentElement.dataset.mode = savedMode as 'light' | 'dark'

// Also set type-voice to match theme
document.documentElement.dataset.typeVoice = VOICE[savedTheme] ?? 'sharp'

createApp(App).use(createPinia()).use(router).mount('#app')
