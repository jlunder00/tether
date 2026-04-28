<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useIntegrationsStore } from '../stores/integrations'

const store = useIntegrationsStore()

onMounted(() => {
  store.fetchAnthropicStatus()
})

// Modal state machine: idle | starting | awaiting_code | completing | error
type ModalPhase = 'idle' | 'starting' | 'awaiting_code' | 'completing' | 'error'
const modalPhase = ref<ModalPhase>('idle')
const codeInput = ref('')
const showConfirmDisconnect = ref(false)
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

async function handleConnect() {
  modalPhase.value = 'starting'
  const url = await store.startAnthropicConnect()
  if (url) {
    modalPhase.value = 'awaiting_code'
  } else {
    modalPhase.value = 'error'
  }
}

async function handleSubmit() {
  if (!codeInput.value.trim()) return
  modalPhase.value = 'completing'
  await store.completeAnthropicConnect(codeInput.value.trim())
  if (store.anthropicConnected) {
    // Success — close modal
    modalPhase.value = 'idle'
    codeInput.value = ''
  } else {
    // Failed — return to awaiting_code phase (error shown inline)
    modalPhase.value = 'awaiting_code'
  }
}

function handleCancel() {
  modalPhase.value = 'idle'
  codeInput.value = ''
}

function handleDisconnectClick() {
  showConfirmDisconnect.value = true
}

function handleDisconnectCancel() {
  showConfirmDisconnect.value = false
}

async function handleDisconnectConfirm() {
  await store.disconnectAnthropic()
  showConfirmDisconnect.value = false
}

async function copyUrl() {
  if (!store.anthropicAuthUrl) return
  try {
    await navigator.clipboard.writeText(store.anthropicAuthUrl)
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    // clipboard not available in test env, ignore
  }
}
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Anthropic Account</h2>
    <div class="bg-gray-800 rounded-xl p-4">
      <!-- Status row -->
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2">
          <!-- Anthropic "A" logo mark -->
          <div class="w-5 h-5 flex-shrink-0 flex items-center justify-center bg-orange-500 rounded text-white font-bold text-xs" aria-hidden="true">
            A
          </div>
          <div>
            <div class="text-sm font-medium text-white">Anthropic Account</div>
            <div v-if="store.anthropicConnected" class="text-xs text-green-400 flex items-center gap-1">
              <span>&#10003;</span>
              <span>Connected</span>
            </div>
            <div v-else class="text-xs text-white/40">Not connected</div>
          </div>
        </div>

        <!-- Action buttons -->
        <div v-if="store.anthropicConnected">
          <template v-if="showConfirmDisconnect">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs text-white/60">Are you sure? You'll need to re-connect.</span>
              <button
                data-testid="anthropic-disconnect-confirm"
                :disabled="store.anthropicLoading"
                @click="handleDisconnectConfirm"
                class="text-sm text-red-400 hover:text-red-300 disabled:opacity-50 border border-red-400/30 hover:border-red-300/50 rounded-lg px-3 py-1.5 transition-colors"
              >
                {{ store.anthropicLoading ? '…' : 'Confirm Disconnect' }}
              </button>
              <button
                @click="handleDisconnectCancel"
                class="text-sm text-white/50 hover:text-white border border-white/20 hover:border-white/40 rounded-lg px-2.5 py-1.5 transition-colors"
              >
                Cancel
              </button>
            </div>
          </template>
          <button
            v-else
            data-testid="anthropic-disconnect"
            :disabled="store.anthropicLoading"
            @click="handleDisconnectClick"
            class="text-sm text-red-400 hover:text-red-300 disabled:opacity-50 border border-red-400/30 hover:border-red-300/50 rounded-lg px-3 py-1.5 transition-colors"
          >
            {{ store.anthropicLoading ? '…' : 'Disconnect' }}
          </button>
        </div>
        <button
          v-else
          data-testid="anthropic-connect"
          :disabled="store.anthropicLoading || modalPhase === 'starting'"
          @click="handleConnect"
          class="text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium rounded-lg px-3 py-1.5 transition-colors"
        >
          {{ (store.anthropicLoading || modalPhase === 'starting') ? '…' : 'Connect' }}
        </button>
      </div>

      <!-- Info text when not connected and modal not open -->
      <p v-if="!store.anthropicConnected && modalPhase === 'idle'" class="text-xs text-white/40">
        Connect your Anthropic account to use Claude-powered features in Tether.
      </p>

      <!-- Error from store when not in modal context -->
      <p v-if="store.anthropicError && modalPhase === 'idle'" class="text-xs text-red-400 mt-2">
        {{ store.anthropicError }}
      </p>

      <!-- Connect Modal (inline overlay inside tile) -->
      <div
        v-if="modalPhase !== 'idle'"
        class="mt-4 border border-white/10 rounded-xl p-4 bg-gray-900/60 space-y-3"
      >
        <h3 class="text-sm font-semibold text-white">Connect your Anthropic account</h3>

        <!-- Starting spinner -->
        <div v-if="modalPhase === 'starting'" class="flex items-center gap-2 text-sm text-white/50">
          <span class="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
          <span>Starting connection...</span>
        </div>

        <!-- Awaiting code phase -->
        <template v-if="modalPhase === 'awaiting_code' || modalPhase === 'completing'">
          <ol class="text-xs text-white/60 space-y-1 list-decimal list-inside">
            <li>Click the link below to authorize on Anthropic's site.</li>
            <li>Copy the code shown on that page.</li>
            <li>Paste it here to complete the connection.</li>
          </ol>

          <!-- Auth URL + Copy button -->
          <div v-if="store.anthropicAuthUrl" class="flex items-center gap-2 flex-wrap">
            <a
              data-testid="anthropic-auth-url"
              :href="store.anthropicAuthUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="text-xs text-indigo-400 hover:text-indigo-300 underline truncate max-w-xs"
            >
              {{ store.anthropicAuthUrl }}
            </a>
            <button
              data-testid="anthropic-copy-url"
              @click="copyUrl"
              class="text-xs text-white/50 hover:text-white border border-white/20 hover:border-white/40 rounded px-2 py-1 transition-colors flex-shrink-0"
            >
              {{ copied ? 'Copied!' : 'Copy URL' }}
            </button>
          </div>

          <!-- Error from store (inline, shown in awaiting_code) -->
          <p v-if="store.anthropicError" class="text-xs text-red-400">
            {{ store.anthropicError }}
          </p>

          <!-- Code input + Submit -->
          <div class="flex items-center gap-2">
            <input
              data-testid="anthropic-code-input"
              v-model="codeInput"
              type="text"
              placeholder="Paste code here"
              :disabled="modalPhase === 'completing'"
              class="flex-1 bg-gray-700 text-white rounded-lg px-3 py-2 text-sm border border-gray-600 focus:outline-none focus:border-indigo-500 placeholder-gray-500 disabled:opacity-50"
              @keydown.enter="handleSubmit"
            />
            <button
              data-testid="anthropic-submit"
              :disabled="!codeInput.trim() || modalPhase === 'completing'"
              @click="handleSubmit"
              class="text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium rounded-lg px-3 py-2 transition-colors flex-shrink-0"
            >
              {{ modalPhase === 'completing' ? '…' : 'Submit' }}
            </button>
          </div>

          <!-- Cancel -->
          <button
            @click="handleCancel"
            :disabled="modalPhase === 'completing'"
            class="text-xs text-white/40 hover:text-white/70 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
        </template>

        <!-- Error phase (start failed) -->
        <template v-if="modalPhase === 'error'">
          <p class="text-xs text-red-400">
            {{ store.anthropicError ?? 'Failed to start connection. Please try again.' }}
          </p>
          <div class="flex gap-2">
            <button
              @click="handleConnect"
              class="text-xs bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg px-3 py-1.5 transition-colors"
            >
              Retry
            </button>
            <button
              @click="handleCancel"
              class="text-xs text-white/40 hover:text-white/70 transition-colors"
            >
              Cancel
            </button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
