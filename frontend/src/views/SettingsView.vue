<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'
import { api } from '../lib/api'
import GoogleCalendarSection from '../components/GoogleCalendarSection.vue'
import AnthropicAccountSection from '../components/AnthropicAccountSection.vue'
import ConnectionsSection from '../components/ConnectionsSection.vue'

const auth = useAuthStore()

// ---------------------------------------------------------------------------
// Appearance / Theme
// ---------------------------------------------------------------------------

const { THEMES, activeTheme, isThemeUnlocked, applyTheme, previewTheme } = useTheme()
const showUpgradeNudge = ref(false)
const upgradeNudgeTheme = ref('')

function onPreviewTheme(themeId: string) {
  previewTheme(themeId)
}

function onSelectTheme(themeId: string) {
  const theme = THEMES.find(t => t.id === themeId)
  if (!theme) return

  // Always apply locally for immediate visual feedback
  previewTheme(themeId)

  if (isThemeUnlocked(theme)) {
    // Persist permanently for unlocked themes
    applyTheme(themeId)
    showUpgradeNudge.value = false
  } else {
    // Locked theme: preview only, show upgrade nudge
    upgradeNudgeTheme.value = theme.name
    showUpgradeNudge.value = true
  }

  // Future: when isPaid && endpoint exists, persist server-side
  // if (isPaid.value) {
  //   fetch('/api/user/preferences', { method: 'PATCH', ... })
  // }
}

// ---------------------------------------------------------------------------
// LLM configuration
// ---------------------------------------------------------------------------

interface LLMConfig {
  models: Record<string, string>
  llm: {
    preferred_backend: string
    thinking_enabled: boolean
    thinking_budget: number
    beacon_score_threshold: number
    beacon_cooldown_minutes: number
  }
  model_roles: string[]
  defaults: { models: Record<string, string>; llm: Record<string, any> }
}

const llmConfig = ref<LLMConfig | null>(null)
const llmStatus = ref<'idle' | 'loading' | 'saving' | 'saved' | 'error'>('idle')
const llmMessage = ref('')
const showAdvanced = ref(false)

const backendOptions = ['anthropic', 'openai', 'openrouter', 'bedrock', 'pipeline']

async function loadLLMConfig() {
  try {
    const resp = await api('/api/llm-config')
    if (resp.ok) llmConfig.value = await resp.json()
  } catch { /* ignore on load failure */ }
}

async function saveLLMConfig() {
  if (!llmConfig.value) return
  llmStatus.value = 'saving'
  llmMessage.value = ''
  try {
    const resp = await api('/api/llm-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        models: llmConfig.value.models,
        llm: llmConfig.value.llm,
      }),
    })
    if (resp.ok) {
      llmStatus.value = 'saved'
      llmMessage.value = 'LLM settings saved.'
      setTimeout(() => { llmStatus.value = 'idle'; llmMessage.value = '' }, 2000)
    } else {
      llmStatus.value = 'error'
      llmMessage.value = 'Failed to save.'
    }
  } catch {
    llmStatus.value = 'error'
    llmMessage.value = 'Network error.'
  }
}

function resetLLMDefaults() {
  if (!llmConfig.value) return
  llmConfig.value.models = { ...llmConfig.value.defaults.models }
  llmConfig.value.llm = { ...llmConfig.value.defaults.llm } as LLMConfig['llm']
}

// ---------------------------------------------------------------------------
// Auto-archive rules
// ---------------------------------------------------------------------------

const archiveDaysCompleted = ref<number | null>(null)
const archiveDaysInactive = ref<number | null>(null)
const archiveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const archiveMessage = ref('')

async function loadArchiveSettings() {
  try {
    const resp = await api('/api/settings')
    if (resp.ok) {
      const data = await resp.json()
      if (data.auto_archive_days_completed)
        archiveDaysCompleted.value = parseInt(data.auto_archive_days_completed, 10)
      if (data.auto_archive_days_inactive)
        archiveDaysInactive.value = parseInt(data.auto_archive_days_inactive, 10)
    }
  } catch { /* ignore */ }
}

async function saveArchiveSettings() {
  archiveStatus.value = 'saving'
  archiveMessage.value = ''
  try {
    const puts: Promise<Response>[] = []
    if (archiveDaysCompleted.value != null) {
      puts.push(api('/api/settings/auto_archive_days_completed', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: String(archiveDaysCompleted.value) }),
      }))
    }
    if (archiveDaysInactive.value != null) {
      puts.push(api('/api/settings/auto_archive_days_inactive', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: String(archiveDaysInactive.value) }),
      }))
    }
    const results = await Promise.all(puts)
    if (results.every(r => r.ok)) {
      archiveStatus.value = 'saved'
      archiveMessage.value = 'Auto-archive rules saved.'
      setTimeout(() => { archiveStatus.value = 'idle'; archiveMessage.value = '' }, 2000)
    } else {
      archiveStatus.value = 'error'
      archiveMessage.value = 'Failed to save.'
    }
  } catch {
    archiveStatus.value = 'error'
    archiveMessage.value = 'Network error.'
  }
}

// Telegram link
const telegramCode = ref('')
const telegramStatus = ref<'idle' | 'loading' | 'success' | 'error'>('idle')
const telegramMessage = ref('')
const telegramLinked = ref(false)

onMounted(async () => {
  loadLLMConfig()
  loadArchiveSettings()
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


</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="max-w-lg mx-auto">
      <!-- Header -->
      <div class="flex items-center gap-3 mb-8">
        <router-link to="/" class="text-[--fg-4] hover:text-[--fg-1] text-sm">← Back</router-link>
        <h1 class="text-xl font-bold">Settings</h1>
      </div>

      <!-- Account -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Account</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-3">
          <div>
            <div class="text-xs text-[--fg-4] mb-1">Username</div>
            <div class="text-[--fg-1] font-medium">{{ auth.user?.username ?? '—' }}</div>
          </div>
        </div>
      </section>

      <!-- Appearance -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Appearance</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">
          <p class="text-xs text-[--fg-4]">Select a theme. Free previews are available for all themes — upgrade to keep a paid theme across sessions.</p>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <button
              v-for="theme in THEMES"
              :key="theme.id"
              @click="onSelectTheme(theme.id)"
              @mouseenter="onPreviewTheme(theme.id)"
              @mouseleave="onPreviewTheme(activeTheme)"
              :title="theme.name"
              :aria-pressed="activeTheme === theme.id"
              class="relative flex flex-col items-start gap-1.5 rounded-lg p-2.5 border transition-all text-left"
              :class="[
                activeTheme === theme.id
                  ? 'border-indigo-500 ring-1 ring-indigo-500'
                  : 'border-[--border-1] hover:border-[--border-2]',
              ]"
            >
              <!-- Canvas/accent swatch -->
              <span
                class="w-full h-6 rounded"
                :style="{ background: `linear-gradient(135deg, ${theme.canvas} 60%, ${theme.accent} 100%)` }"
              />
              <span class="text-xs text-[--fg-2] font-medium leading-tight">{{ theme.name }}</span>
              <!-- Tier badge -->
              <span
                v-if="theme.tier !== 'free'"
                class="absolute top-1.5 right-1.5 text-[9px] font-bold uppercase tracking-wide px-1 py-0.5 rounded"
                :class="isThemeUnlocked(theme) ? 'bg-[--status-done-bg] text-[--status-done-fg]' : 'bg-[--bg-elev-3] text-[--fg-4]'"
              >{{ isThemeUnlocked(theme) ? 'oss' : 'paid' }}</span>
            </button>
          </div>

          <!-- Upgrade nudge -->
          <div
            v-if="showUpgradeNudge"
            class="flex items-center justify-between gap-3 rounded-lg bg-indigo-900/40 border border-indigo-700/50 px-3 py-2.5 text-sm"
          >
            <span class="text-[--fg-2]">
              <strong class="text-[--fg-1]">{{ upgradeNudgeTheme }}</strong> is a paid theme — upgrade to keep it.
            </span>
            <button
              @click="showUpgradeNudge = false"
              class="text-[--fg-5] hover:text-[--fg-2] text-xs shrink-0"
              aria-label="Dismiss"
            >✕</button>
          </div>
        </div>
      </section>

      <!-- Change Password -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Change Password</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-3">
          <input
            type="password"
            disabled
            placeholder="Current password"
            class="w-full bg-[--bg-elev-2] text-[--fg-5] rounded-lg px-3 py-2 text-sm border border-[--border-1] cursor-not-allowed"
          />
          <input
            type="password"
            disabled
            placeholder="New password"
            class="w-full bg-[--bg-elev-2] text-[--fg-5] rounded-lg px-3 py-2 text-sm border border-[--border-1] cursor-not-allowed"
          />
          <input
            type="password"
            disabled
            placeholder="Confirm new password"
            class="w-full bg-[--bg-elev-2] text-[--fg-5] rounded-lg px-3 py-2 text-sm border border-[--border-1] cursor-not-allowed"
          />
          <p class="text-xs text-[--fg-5]">Password change coming soon.</p>
        </div>
      </section>

      <!-- Telegram Link -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Telegram</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4">
          <div v-if="telegramLinked" class="flex items-center gap-2 text-[--status-done-fg] text-sm">
            <span>✓</span>
            <span>Telegram linked</span>
          </div>
          <template v-else>
            <p class="text-sm text-[--fg-3] mb-3">
              Send <code class="bg-[--bg-elev-2] px-1 rounded">/link</code> to your Tether bot to get a 6-digit code, then enter it below.
            </p>
            <div class="flex gap-2">
              <input
                v-model="telegramCode"
                type="text"
                inputmode="numeric"
                maxlength="6"
                placeholder="123456"
                class="flex-1 bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 placeholder:text-[--fg-5]"
                @keydown.enter="linkTelegram"
              />
              <button
                @click="linkTelegram"
                :disabled="telegramStatus === 'loading' || !telegramCode.trim()"
                class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-[--fg-1] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
              >
                {{ telegramStatus === 'loading' ? '…' : 'Link' }}
              </button>
            </div>
            <p v-if="telegramMessage" :class="telegramStatus === 'success' ? 'text-[--status-done-fg]' : 'text-[--status-block-fg]'" class="text-sm mt-2">
              {{ telegramMessage }}
            </p>
          </template>
        </div>
      </section>

      <!-- Connections (Friends) -->
      <ConnectionsSection />

      <!-- Google Calendar Integration -->
      <GoogleCalendarSection />

      <!-- Anthropic Account Integration -->
      <AnthropicAccountSection />

      <!-- OAuth Connections -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">OAuth Connections</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-2">
          <button
            disabled
            class="w-full bg-[--bg-elev-2] text-[--fg-4] text-sm font-medium rounded-lg px-4 py-2.5 border border-[--border-1] flex items-center gap-2 cursor-not-allowed"
          >
            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd" />
            </svg>
            Connect GitHub
            <span class="ml-auto text-[10px] bg-[--bg-elev-3] text-[--fg-4] rounded px-1.5 py-0.5 font-normal tracking-wide">coming soon</span>
          </button>
          <button
            disabled
            class="w-full bg-[--bg-elev-2] text-[--fg-4] text-sm font-medium rounded-lg px-4 py-2.5 border border-[--border-1] flex items-center gap-2 cursor-not-allowed"
          >
            <svg class="w-4 h-4 opacity-40" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Connect Google
            <span class="ml-auto text-[10px] bg-[--bg-elev-3] text-[--fg-4] rounded px-1.5 py-0.5 font-normal tracking-wide">coming soon</span>
          </button>
        </div>
      </section>

      <!-- Auto-Archive Rules -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Auto-Archive Rules</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">
          <p class="text-sm text-[--fg-3]">
            Automatically archive context nodes when they become stale. Leave blank to disable a rule.
          </p>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-[--fg-4] mb-1 block">Archive after completion (days)</label>
              <input
                type="number"
                v-model.number="archiveDaysCompleted"
                min="1"
                placeholder="e.g. 7"
                class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 placeholder:text-[--fg-5]"
              />
              <p class="text-xs text-[--fg-5] mt-1">Archive nodes whose tasks are all done for X days</p>
            </div>
            <div>
              <label class="text-xs text-[--fg-4] mb-1 block">Archive after inactivity (days)</label>
              <input
                type="number"
                v-model.number="archiveDaysInactive"
                min="1"
                placeholder="e.g. 30"
                class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 placeholder:text-[--fg-5]"
              />
              <p class="text-xs text-[--fg-5] mt-1">Archive nodes with no updates for X days</p>
            </div>
          </div>
          <div class="flex gap-2 pt-1">
            <button
              @click="saveArchiveSettings"
              :disabled="archiveStatus === 'saving'"
              class="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-[--fg-1] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
            >
              {{ archiveStatus === 'saving' ? 'Saving...' : 'Save' }}
            </button>
          </div>
          <p v-if="archiveMessage" :class="archiveStatus === 'saved' ? 'text-[--status-done-fg]' : 'text-[--status-block-fg]'" class="text-sm">
            {{ archiveMessage }}
          </p>
        </div>
      </section>

      <!-- LLM Configuration -->
      <section v-if="llmConfig" class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">LLM Configuration</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">

          <!-- Preferred Backend -->
          <div>
            <label class="text-xs text-[--fg-4] mb-1 block">Preferred Backend</label>
            <select
              v-model="llmConfig.llm.preferred_backend"
              class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500"
            >
              <option v-for="b in backendOptions" :key="b" :value="b">{{ b }}</option>
            </select>
          </div>

          <!-- Extended Thinking -->
          <div class="flex items-center justify-between">
            <div>
              <div class="text-sm text-[--fg-1]">Extended Thinking</div>
              <div class="text-xs text-[--fg-4]">Allows deeper reasoning before responding</div>
            </div>
            <button
              @click="llmConfig.llm.thinking_enabled = !llmConfig.llm.thinking_enabled"
              :class="llmConfig.llm.thinking_enabled ? 'bg-indigo-600' : 'bg-[--bg-elev-3]'"
              class="relative w-11 h-6 rounded-full transition-colors"
            >
              <span
                :class="llmConfig.llm.thinking_enabled ? 'translate-x-5' : 'translate-x-0.5'"
                class="inline-block w-5 h-5 bg-white rounded-full transition-transform transform mt-0.5"
              />
            </button>
          </div>

          <!-- Thinking Budget -->
          <div v-if="llmConfig.llm.thinking_enabled">
            <label class="text-xs text-[--fg-4] mb-1 block">
              Thinking Budget: {{ llmConfig.llm.thinking_budget.toLocaleString() }} tokens
            </label>
            <input
              type="range"
              v-model.number="llmConfig.llm.thinking_budget"
              min="2000"
              max="32000"
              step="1000"
              class="w-full accent-indigo-500"
            />
            <div class="flex justify-between text-xs text-[--fg-5] mt-1">
              <span>2K</span><span>16K</span><span>32K</span>
            </div>
          </div>

          <!-- Beacon Settings -->
          <div class="border-t border-[--border-1] pt-3 mt-3">
            <div class="text-sm text-[--fg-1] mb-2">Beacon (Background Agent)</div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="text-xs text-[--fg-4] mb-1 block">Score Threshold</label>
                <input
                  type="number"
                  v-model.number="llmConfig.llm.beacon_score_threshold"
                  min="1" max="50"
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label class="text-xs text-[--fg-4] mb-1 block">Cooldown (min)</label>
                <input
                  type="number"
                  v-model.number="llmConfig.llm.beacon_cooldown_minutes"
                  min="5" max="120"
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500"
                />
              </div>
            </div>
          </div>

          <!-- Advanced: Model Roles -->
          <div class="border-t border-[--border-1] pt-3 mt-3">
            <button
              @click="showAdvanced = !showAdvanced"
              class="text-sm text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
            >
              <span :class="showAdvanced ? 'rotate-90' : ''" class="transition-transform inline-block">&#9656;</span>
              Advanced: Model Assignments
            </button>
            <div v-if="showAdvanced" class="mt-3 space-y-2">
              <div v-for="role in llmConfig.model_roles" :key="role">
                <label class="text-xs text-[--fg-4] mb-1 block">{{ role.replace(/_/g, ' ') }}</label>
                <input
                  type="text"
                  v-model="llmConfig.models[role]"
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 font-mono text-xs"
                />
              </div>
            </div>
          </div>

          <!-- Save / Reset -->
          <div class="flex gap-2 pt-2">
            <button
              @click="saveLLMConfig"
              :disabled="llmStatus === 'saving'"
              class="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-[--fg-1] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
            >
              {{ llmStatus === 'saving' ? 'Saving...' : 'Save' }}
            </button>
            <button
              @click="resetLLMDefaults"
              class="bg-[--bg-elev-2] hover:bg-[--bg-elev-3] text-[--fg-1] text-sm font-medium rounded-lg px-4 py-2 border border-[--border-1] transition-colors"
            >
              Reset Defaults
            </button>
          </div>
          <p v-if="llmMessage" :class="llmStatus === 'saved' ? 'text-[--status-done-fg]' : 'text-[--status-block-fg]'" class="text-sm">
            {{ llmMessage }}
          </p>
        </div>
      </section>
    </div>
  </div>
</template>
