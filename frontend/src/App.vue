<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from './stores/auth'
import { useRouter } from 'vue-router'
import { loadPremiumThemes } from './composables/usePremiumThemes'
import BotChat from './components/BotChat.vue'
import SlideOverStack from './components/SlideOverStack.vue'

const authStore = useAuthStore()
const router = useRouter()

// Load premium theme CSS once the user is known to be authenticated.
// isPaid is always false today; this fires when backend adds the field.
watch(
  () => authStore.user,
  (user) => {
    if (user && (user as any).is_paid) {
      // token not available client-side via cookie auth — pass empty string;
      // the endpoint will use session cookie instead when implemented
      loadPremiumThemes('')
    }
  },
  { immediate: true },
)
const chatOpen = ref(false)

async function logout() {
  await authStore.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white crt" style="position: relative">
    <!-- Navigation bar (shown when authenticated) -->
    <nav v-if="authStore.isAuthenticated"
         class="flex items-center justify-between px-6 py-3 border-b border-white/10 bg-gray-900/80 backdrop-blur-sm sticky top-0 z-10">
      <div class="flex items-center gap-6">
        <span class="text-lg font-bold tracking-tight">Tether</span>
        <div class="flex items-center gap-1">
          <router-link to="/dashboard"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       :class="$route.path.startsWith('/dashboard') ? 'bg-white/20 text-white' : 'text-white/60'">
            Dashboard
          </router-link>
          <router-link to="/calendar"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       :class="$route.path.startsWith('/calendar') ? 'bg-white/20 text-white' : 'text-white/60'">
            Calendar
          </router-link>
          <router-link to="/plan/day"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       active-class="bg-white/20 text-white"
                       :class="$route.path.startsWith('/plan') ? 'bg-white/20 text-white' : 'text-white/60'">
            Plan
          </router-link>
          <router-link to="/context"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       active-class="bg-white/20 text-white"
                       :class="$route.path === '/context' ? 'bg-white/20 text-white' : 'text-white/60'">
            Context
          </router-link>
          <router-link to="/anchors"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       active-class="bg-white/20 text-white"
                       :class="$route.path === '/anchors' ? 'bg-white/20 text-white' : 'text-white/60'">
            Anchors
          </router-link>
          <router-link to="/kanban"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       :class="$route.path.startsWith('/kanban') ? 'bg-white/20 text-white' : 'text-white/60'">
            Kanban
          </router-link>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <!-- Chat toggle pill -->
        <button
          @click="chatOpen = !chatOpen"
          class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
          :class="chatOpen ? 'bg-indigo-600/40 text-white' : 'text-white/60'"
          title="Toggle chat (Ctrl+/)"
        >
          Chat
        </button>

        <router-link v-if="authStore.user?.is_admin" to="/admin"
                     class="text-xs text-white/40 hover:text-white/80 border border-white/10 rounded px-2 py-1 transition-colors">
          Admin
        </router-link>
        <router-link to="/settings"
                     class="text-white/40 hover:text-white/80 transition-colors p-1.5 rounded-lg hover:bg-white/10"
                     title="Settings">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </router-link>
        <button @click="logout"
                class="text-xs text-white/40 hover:text-white/80 border border-white/10 rounded px-2 py-1 transition-colors ml-1">
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
          class="w-[420px] flex-shrink-0 border-l border-white/10 bg-gray-900 flex flex-col"
        >
          <BotChat @close="chatOpen = false" />
        </aside>
      </Transition>
    </div>

    <!-- Unauthenticated: just render the view -->
    <router-view v-if="!authStore.isAuthenticated" />

    <!-- Global slide-over panel stack (outside router-view so it persists across routes) -->
    <SlideOverStack v-if="authStore.isAuthenticated" />
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
