<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const email = ref('')
const password = ref('')
const inviteToken = ref('')
const error = ref('')
const loading = ref(false)

onMounted(() => {
  if (route.query.invite) {
    inviteToken.value = String(route.query.invite)
  }
})

async function handleRegister() {
  error.value = ''
  loading.value = true
  try {
    await auth.register(username.value, email.value, password.value, inviteToken.value || undefined)
    router.push({ name: 'day' })
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 flex items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <h1 class="text-3xl font-bold text-white text-center mb-8">Tether</h1>
      <p class="text-gray-400 text-center text-sm mb-6">Create your account</p>

      <form @submit.prevent="handleRegister" class="space-y-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1" for="username">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            class="w-full bg-gray-800 text-white rounded-lg px-4 py-2.5 border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-500"
            placeholder="yourname"
          />
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-1" for="email">Email</label>
          <input
            id="email"
            v-model="email"
            type="email"
            autocomplete="email"
            required
            class="w-full bg-gray-800 text-white rounded-lg px-4 py-2.5 border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-500"
            placeholder="you@example.com"
          />
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-1" for="password">Password</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            required
            class="w-full bg-gray-800 text-white rounded-lg px-4 py-2.5 border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-500"
            placeholder="••••••••"
          />
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-1" for="invite">Invite token <span class="text-gray-600">(optional)</span></label>
          <input
            id="invite"
            v-model="inviteToken"
            type="text"
            class="w-full bg-gray-800 text-white rounded-lg px-4 py-2.5 border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-500"
            placeholder="abc123"
          />
        </div>

        <div v-if="error" class="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">
          {{ error }}
        </div>

        <button
          type="submit"
          :disabled="loading"
          class="w-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium rounded-lg px-4 py-2.5 transition-colors"
        >
          {{ loading ? 'Creating account…' : 'Create account' }}
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-gray-500">
        Already have an account?
        <router-link to="/login" class="text-indigo-400 hover:text-indigo-300 ml-1">Sign in</router-link>
      </p>
    </div>
  </div>
</template>
