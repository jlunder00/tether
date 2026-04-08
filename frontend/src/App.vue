<script setup lang="ts">
import { useAuthStore } from './stores/auth'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

async function logout() {
  await authStore.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white">
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
          <router-link to="/backlog"
                       class="px-3 py-1.5 rounded-lg text-sm transition-colors hover:bg-white/10"
                       :class="$route.path.startsWith('/backlog') ? 'bg-white/20 text-white' : 'text-white/60'">
            Backlog
          </router-link>
        </div>
      </div>
      <div class="flex items-center gap-2">
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

    <router-view />
  </div>
</template>
