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
  <div class="min-h-screen bg-[--bg-canvas] flex items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <h1 class="text-3xl font-bold text-[--fg-1] text-center mb-8">Tether</h1>
      <p class="text-[--fg-3] text-center text-sm mb-6">Create your account</p>

      <form @submit.prevent="handleRegister" class="space-y-4">
        <div>
          <label class="block text-sm text-[--fg-3] mb-1" for="username">Username</label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            class="w-full bg-[--bg-elev-1] text-[--fg-1] rounded-lg px-4 py-2.5 border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            placeholder="yourname"
          />
        </div>

        <div>
          <label class="block text-sm text-[--fg-3] mb-1" for="email">Email</label>
          <input
            id="email"
            v-model="email"
            type="email"
            autocomplete="email"
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
            autocomplete="new-password"
            required
            class="w-full bg-[--bg-elev-1] text-[--fg-1] rounded-lg px-4 py-2.5 border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            placeholder="••••••••"
          />
        </div>

        <div>
          <label class="block text-sm text-[--fg-3] mb-1" for="invite">Invite token <span class="text-[--fg-5]">(optional)</span></label>
          <input
            id="invite"
            v-model="inviteToken"
            type="text"
            class="w-full bg-[--bg-elev-1] text-[--fg-1] rounded-lg px-4 py-2.5 border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            placeholder="abc123"
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
          {{ loading ? 'Creating account…' : 'Create account' }}
        </button>
      </form>

      <p class="mt-6 text-center text-sm text-[--fg-4]">
        Already have an account?
        <router-link to="/login" class="text-[--accent] hover:opacity-80 ml-1">Sign in</router-link>
      </p>
    </div>
  </div>
</template>
