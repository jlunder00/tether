<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const login = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(login.value, password.value)
    router.push({ name: 'day' })
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Login failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] flex items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <h1 class="text-3xl font-bold text-[--fg-1] text-center mb-8">Tether</h1>

      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-sm text-[--fg-3] mb-1" for="login">Username or email</label>
          <input
            id="login"
            v-model="login"
            type="text"
            autocomplete="username"
            required
            class="w-full bg-[--bg-elev-1] text-[--fg-1] rounded-lg px-4 py-2.5 border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            placeholder="you@example.com"
          />
        </div>

        <div>
          <label class="block text-sm text-[--fg-3] mb-1" for="password">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            class="w-full bg-[--bg-elev-1] text-[--fg-1] rounded-lg px-4 py-2.5 border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            placeholder="••••••••"
          />
        </div>

        <div v-if="error" class="text-[--status-block-fg] text-sm bg-[--status-block-bg] border border-[--status-block-fg]/30 rounded-lg px-3 py-2">
          {{ error }}
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] font-medium rounded-lg px-4 py-2.5 transition-colors"
        >
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>

      <div class="mt-4 space-y-2">
        <button
          @click="auth.loginWithGithub()"
          class="w-full bg-[--bg-elev-1] hover:bg-[--bg-elev-2] text-[--fg-1] font-medium rounded-lg px-4 py-2.5 border border-[--border-1] transition-colors flex items-center justify-center gap-2"
        >
          <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd" />
          </svg>
          Sign in with GitHub
        </button>

        <button
          @click="auth.loginWithGoogle()"
          class="w-full bg-[--bg-elev-1] hover:bg-[--bg-elev-2] text-[--fg-1] font-medium rounded-lg px-4 py-2.5 border border-[--border-1] transition-colors flex items-center justify-center gap-2"
        >
          <svg class="w-5 h-5" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          Sign in with Google
        </button>
      </div>

      <p class="mt-6 text-center text-sm text-[--fg-4]">
        Don't have an account?
        <router-link to="/register" class="text-[--accent] hover:opacity-80 ml-1">Register</router-link>
      </p>
    </div>
  </div>
</template>
