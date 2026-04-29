import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  define: {
    // Set TETHER_EDITION to 'cloud' by default; override with VITE_TETHER_EDITION env var
    __TETHER_EDITION__: JSON.stringify(process.env.VITE_TETHER_EDITION ?? 'cloud'),
  },
})
