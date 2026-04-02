<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

// Telegram link
const telegramCode = ref('')
const telegramStatus = ref<'idle' | 'loading' | 'success' | 'error'>('idle')
const telegramMessage = ref('')
const telegramLinked = ref(false)

// Check if already linked by reading from /auth/me response (is_admin field present)
// We'll just let user try — success/error from API handles it
onMounted(async () => {
  try {
    const resp = await fetch('/auth/me', { credentials: 'include' })
    if (resp.ok) {
      const data = await resp.json()
      telegramLinked.value = !!data.telegram_linked
    }
  } catch {
    // ignore
  }
})

async function linkTelegram() {
  if (!telegramCode.value.trim()) return
  telegramStatus.value = 'loading'
  telegramMessage.value = ''
  try {
    const resp = await fetch('/auth/telegram-link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ code: telegramCode.value.trim() }),
    })
    if (resp.ok) {
      telegramStatus.value = 'success'
      telegramMessage.value = 'Telegram linked successfully.'
      telegramLinked.value = true
      telegramCode.value = ''
    } else {
      const data = await resp.json().catch(() => ({}))
      telegramStatus.value = 'error'
      telegramMessage.value = data.detail || 'Failed to link Telegram.'
    }
  } catch {
    telegramStatus.value = 'error'
    telegramMessage.value = 'Network error.'
  }
}

function connectGithub() {
  window.location.href = '/auth/github?link=1'
}

function connectGoogle() {
  window.location.href = '/auth/google?link=1'
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="max-w-lg mx-auto">
      <!-- Header -->
      <div class="flex items-center gap-3 mb-8">
        <router-link to="/" class="text-white/40 hover:text-white text-sm">← Back</router-link>
        <h1 class="text-xl font-bold">Settings</h1>
      </div>

      <!-- Account -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Account</h2>
        <div class="bg-gray-800 rounded-xl p-4 space-y-3">
          <div>
            <div class="text-xs text-gray-400 mb-1">Username</div>
            <div class="text-white font-medium">{{ auth.user?.username ?? '—' }}</div>
          </div>
        </div>
      </section>

      <!-- Change Password -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Change Password</h2>
        <div class="bg-gray-800 rounded-xl p-4 space-y-3">
          <input
            type="password"
            disabled
            placeholder="Current password"
            class="w-full bg-gray-700/50 text-gray-500 rounded-lg px-3 py-2 text-sm border border-gray-700 cursor-not-allowed"
          />
          <input
            type="password"
            disabled
            placeholder="New password"
            class="w-full bg-gray-700/50 text-gray-500 rounded-lg px-3 py-2 text-sm border border-gray-700 cursor-not-allowed"
          />
          <input
            type="password"
            disabled
            placeholder="Confirm new password"
            class="w-full bg-gray-700/50 text-gray-500 rounded-lg px-3 py-2 text-sm border border-gray-700 cursor-not-allowed"
          />
          <p class="text-xs text-white/30">Password change coming soon.</p>
        </div>
      </section>

      <!-- Telegram Link -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Telegram</h2>
        <div class="bg-gray-800 rounded-xl p-4">
          <div v-if="telegramLinked" class="flex items-center gap-2 text-green-400 text-sm">
            <span>✓</span>
            <span>Telegram linked</span>
          </div>
          <template v-else>
            <p class="text-sm text-white/60 mb-3">
              Send <code class="bg-gray-700 px-1 rounded">/link</code> to your Tether bot to get a 6-digit code, then enter it below.
            </p>
            <div class="flex gap-2">
              <input
                v-model="telegramCode"
                type="text"
                inputmode="numeric"
                maxlength="6"
                placeholder="123456"
                class="flex-1 bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-indigo-500 placeholder-gray-500"
                @keydown.enter="linkTelegram"
              />
              <button
                @click="linkTelegram"
                :disabled="telegramStatus === 'loading' || !telegramCode.trim()"
                class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
              >
                {{ telegramStatus === 'loading' ? '…' : 'Link' }}
              </button>
            </div>
            <p v-if="telegramMessage" :class="telegramStatus === 'success' ? 'text-green-400' : 'text-red-400'" class="text-sm mt-2">
              {{ telegramMessage }}
            </p>
          </template>
        </div>
      </section>

      <!-- OAuth Connections -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">OAuth Connections</h2>
        <div class="bg-gray-800 rounded-xl p-4 space-y-2">
          <button
            @click="connectGithub"
            class="w-full bg-gray-700 hover:bg-gray-600 text-white text-sm font-medium rounded-lg px-4 py-2.5 border border-gray-600 transition-colors flex items-center gap-2"
          >
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd" />
            </svg>
            Connect GitHub
          </button>
          <button
            @click="connectGoogle"
            class="w-full bg-gray-700 hover:bg-gray-600 text-white text-sm font-medium rounded-lg px-4 py-2.5 border border-gray-600 transition-colors flex items-center gap-2"
          >
            <svg class="w-4 h-4" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Connect Google
          </button>
        </div>
      </section>
    </div>
  </div>
</template>
