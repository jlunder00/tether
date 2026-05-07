<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useTheme } from '../composables/useTheme'
import { api } from '../lib/api'
import GoogleCalendarSection from '../components/GoogleCalendarSection.vue'
import AnthropicAccountSection from '../components/AnthropicAccountSection.vue'
import ConnectionsSection from '../components/ConnectionsSection.vue'
import ApiKeysSection from '../components/ApiKeysSection.vue'

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
                  ? 'border-[--accent] ring-1 ring-[--accent]'
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
            class="flex items-center justify-between gap-3 rounded-lg bg-[--accent-veil] border border-[--accent-soft] px-3 py-2.5 text-sm"
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
                class="flex-1 bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
                @keydown.enter="linkTelegram"
              />
              <button
                @click="linkTelegram"
                :disabled="telegramStatus === 'loading' || !telegramCode.trim()"
                class="bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
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

      <!-- API Keys -->
      <ApiKeysSection />

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
                class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
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
                class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
              />
              <p class="text-xs text-[--fg-5] mt-1">Archive nodes with no updates for X days</p>
            </div>
          </div>
          <div class="flex gap-2 pt-1">
            <button
              @click="saveArchiveSettings"
              :disabled="archiveStatus === 'saving'"
              class="flex-1 bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
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
              class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent]"
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
              :class="llmConfig.llm.thinking_enabled ? 'bg-[--accent]' : 'bg-[--bg-elev-3]'"
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
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent]"
                />
              </div>
              <div>
                <label class="text-xs text-[--fg-4] mb-1 block">Cooldown (min)</label>
                <input
                  type="number"
                  v-model.number="llmConfig.llm.beacon_cooldown_minutes"
                  min="5" max="120"
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent]"
                />
              </div>
            </div>
          </div>

          <!-- Advanced: Model Roles -->
          <div class="border-t border-[--border-1] pt-3 mt-3">
            <button
              @click="showAdvanced = !showAdvanced"
              class="text-sm text-[--accent] hover:opacity-80 flex items-center gap-1"
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
                  class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] font-mono text-xs"
                />
              </div>
            </div>
          </div>

          <!-- Save / Reset -->
          <div class="flex gap-2 pt-2">
            <button
              @click="saveLLMConfig"
              :disabled="llmStatus === 'saving'"
              class="flex-1 bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
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
