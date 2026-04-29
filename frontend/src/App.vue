<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from './stores/auth'
import { useRouter } from 'vue-router'
import { loadPremiumThemes, unloadPremiumThemes } from './composables/usePremiumThemes'
import BotChat from './components/BotChat.vue'
import SlideOverStack from './components/SlideOverStack.vue'
import ThemeDrawer from './components/ThemeDrawer.vue'
import { useTheme } from './composables/useTheme'

const authStore = useAuthStore()
const router = useRouter()
const { activeMode, setMode } = useTheme()

function toggleMode() {
  setMode(activeMode.value === 'dark' ? 'light' : 'dark')
}

// Load premium theme CSS once the user is known to be authenticated.
// isPaid is always false today; this fires when backend adds the field.
watch(
  () => authStore.user,
  (user) => {
    if (user?.is_paid) {
      // Cookie auth handles identity; token param reserved for future API-key support
      loadPremiumThemes()
    } else {
      // Remove premium CSS when user logs out or loses entitlement
      unloadPremiumThemes()
    }
  },
  { immediate: true },
)
const chatOpen = ref(false)
const themeDrawerOpen = ref(false)

async function logout() {
  await authStore.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="crt relative min-h-screen bg-[--bg-canvas] text-[--fg-1]">
    <!-- Navigation bar (shown when authenticated) -->
    <nav v-if="authStore.isAuthenticated"
         class="flex items-center justify-between px-6 py-3 border-b border-[--border-1] bg-[--bg-canvas-veil] backdrop-blur-sm sticky top-0 z-10">
      <div class="flex items-center gap-6">
        <span class="text-lg font-bold tracking-tight">Tether</span>
        <div class="flex items-center gap-1">
          <router-link to="/dashboard"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       :class="$route.path.startsWith('/dashboard') ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Dashboard
          </router-link>
          <router-link to="/calendar"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       :class="$route.path.startsWith('/calendar') ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Calendar
          </router-link>
          <router-link to="/plan/day"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       active-class="bg-[--bg-elev-4] text-[--fg-1]"
                       :class="$route.path.startsWith('/plan') ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Plan
          </router-link>
          <router-link to="/context"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       active-class="bg-[--bg-elev-4] text-[--fg-1]"
                       :class="$route.path === '/context' ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Context
          </router-link>
          <router-link to="/anchors"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       active-class="bg-[--bg-elev-4] text-[--fg-1]"
                       :class="$route.path === '/anchors' ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Anchors
          </router-link>
          <router-link to="/kanban"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
                       :class="$route.path.startsWith('/kanban') ? 'bg-[--bg-elev-4] text-[--fg-1]' : 'text-[--fg-3]'">
            Kanban
          </router-link>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <!-- Chat toggle pill -->
        <button
          @click="chatOpen = !chatOpen"
          class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-[--bg-elev-3]"
          :class="chatOpen ? 'bg-indigo-600/40 text-[--fg-1]' : 'text-[--fg-3]'"
          title="Toggle chat (Ctrl+/)"
        >
          Chat
        </button>

        <button @click="toggleMode"
                class="text-[--fg-3] hover:text-[--fg-1] transition-colors p-1.5 rounded-lg hover:bg-[--bg-elev-3] text-sm leading-none"
                :title="activeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'"
                :aria-label="activeMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'">
          <span v-if="activeMode === 'dark'">☀</span>
          <span v-else>☾</span>
        </button>

        <button
          @click="themeDrawerOpen = true"
          data-testid="theme-drawer-trigger"
          class="text-[--fg-3] hover:text-[--fg-1] transition-colors p-1.5 rounded-lg hover:bg-[--bg-elev-3]"
          title="Theme"
          aria-label="Open theme picker"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
          </svg>
        </button>

        <router-link v-if="authStore.user?.is_admin" to="/admin"
                     class="text-xs text-[--fg-3] hover:text-[--fg-1] border border-[--border-1] rounded px-2 py-1 transition-colors">
          Admin
        </router-link>
        <router-link to="/settings"
                     class="text-[--fg-3] hover:text-[--fg-1] transition-colors p-1.5 rounded-lg hover:bg-[--bg-elev-3]"
                     title="Settings">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </router-link>
        <button @click="logout"
                class="text-xs text-[--fg-3] hover:text-[--fg-1] border border-[--border-1] rounded px-2 py-1 transition-colors ml-1">
          Logout
        </button>
      </div>
    </nav>

    <!-- Main layout: content + optional chat panel -->
    <div class="flex h-[calc(100vh-49px)]" v-if="authStore.isAuthenticated">
      <div class="flex-1 overflow-auto">
        <router-view />
      </div>

      <!-- Slide-in chat panel -->
      <Transition name="chat-slide">
        <aside
          v-if="chatOpen"
          class="w-[420px] flex-shrink-0 border-l border-[--border-1] bg-[--bg-canvas] flex flex-col"
        >
          <BotChat @close="chatOpen = false" />
        </aside>
      </Transition>
    </div>

    <!-- Unauthenticated: just render the view -->
    <router-view v-if="!authStore.isAuthenticated" />

    <!-- Global slide-over panel stack (outside router-view so it persists across routes) -->
    <SlideOverStack v-if="authStore.isAuthenticated" />

    <!-- Global theme picker drawer -->
    <ThemeDrawer v-if="authStore.isAuthenticated" v-model="themeDrawerOpen" />
  </div>
</template>

<style scoped>
.chat-slide-enter-active,
.chat-slide-leave-active {
  transition: width 0.2s ease, opacity 0.2s ease;
  overflow: hidden;
}
.chat-slide-enter-from,
.chat-slide-leave-to {
  width: 0;
  opacity: 0;
}
.chat-slide-enter-to,
.chat-slide-leave-from {
  width: 420px;
  opacity: 1;
}
</style>
