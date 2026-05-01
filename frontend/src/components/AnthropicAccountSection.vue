<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
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
  if (modalPhase.value !== 'idle') return
  store.clearAnthropicFlowState()
  modalPhase.value = 'starting'
  const url = await store.startAnthropicConnect()
  if (url) {
    modalPhase.value = 'awaiting_code'
  } else {
    modalPhase.value = 'error'
  }
}

async function handleSubmit() {
  if (modalPhase.value === 'completing') return
  if (!codeInput.value.trim()) return
  modalPhase.value = 'completing'
  await store.completeAnthropicConnect(codeInput.value.trim())
  if (store.anthropicConnected) {
    // Success — close modal
    store.clearAnthropicFlowState()
    modalPhase.value = 'idle'
    codeInput.value = ''
  } else {
    // Failed — return to awaiting_code phase (error shown inline)
    modalPhase.value = 'awaiting_code'
  }
}

function handleCancel() {
  store.clearAnthropicFlowState()
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
  if (!store.anthropicError) {
    showConfirmDisconnect.value = false
  }
}

onUnmounted(() => {
  if (copiedTimer) clearTimeout(copiedTimer)
})

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
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Anthropic Account</h2>
    <div class="bg-[--bg-elev-1] rounded-xl p-4">
      <!-- Status row -->
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2">
          <!-- Anthropic "A" logo mark -->
          <div class="w-5 h-5 flex-shrink-0 flex items-center justify-center bg-orange-500 rounded text-white font-bold text-xs" aria-hidden="true">
            A
          </div>
          <div>
            <div class="text-sm font-medium text-[--fg-1]">Anthropic Account</div>
            <div v-if="store.anthropicConnected" class="text-xs text-[--status-done-fg] flex items-center gap-1">
              <span>&#10003;</span>
              <span>Connected</span>
            </div>
            <div v-else class="text-xs text-[--fg-4]">Not connected</div>
          </div>
        </div>

        <!-- Action buttons -->
        <div v-if="store.anthropicConnected">
          <template v-if="showConfirmDisconnect">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-xs text-[--fg-3]">Are you sure? You'll need to re-connect.</span>
              <button
                data-testid="anthropic-disconnect-confirm"
                :disabled="store.anthropicLoading"
                @click="handleDisconnectConfirm"
                class="text-sm text-[--status-block-fg] hover:opacity-80 disabled:opacity-50 border border-[--border-1] hover:border-[--border-2] rounded-lg px-3 py-1.5 transition-colors"
              >
                {{ store.anthropicLoading ? '…' : 'Confirm Disconnect' }}
              </button>
              <button
                @click="handleDisconnectCancel"
                class="text-sm text-[--fg-3] hover:text-[--fg-1] border border-[--border-1] hover:border-[--border-2] rounded-lg px-2.5 py-1.5 transition-colors"
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
            class="text-sm text-[--status-block-fg] hover:opacity-80 disabled:opacity-50 border border-[--border-1] hover:border-[--border-2] rounded-lg px-3 py-1.5 transition-colors"
          >
            {{ store.anthropicLoading ? '…' : 'Disconnect' }}
          </button>
        </div>
        <button
          v-else
          data-testid="anthropic-connect"
          :disabled="store.anthropicLoading || modalPhase === 'starting'"
          @click="handleConnect"
          class="text-sm bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] font-medium rounded-lg px-3 py-1.5 transition-colors"
        >
          {{ (store.anthropicLoading || modalPhase === 'starting') ? '…' : 'Connect' }}
        </button>
      </div>

      <!-- Error shown in connected view (e.g. disconnect failure) -->
      <p v-if="store.anthropicConnected && store.anthropicError" class="text-xs text-[--status-block-fg] mt-2">{{ store.anthropicError }}</p>

      <!-- Info text when not connected and modal not open -->
      <p v-if="!store.anthropicConnected && modalPhase === 'idle'" class="text-xs text-[--fg-4]">
        Connect your Anthropic account to use Claude-powered features in Tether.
      </p>

      <!-- Error from store when not in modal context -->
      <p v-if="store.anthropicError && modalPhase === 'idle'" class="text-xs text-[--status-block-fg] mt-2">
        {{ store.anthropicError }}
      </p>

      <!-- Connect Modal (inline overlay inside tile) -->
      <div
        v-if="modalPhase !== 'idle'"
        class="mt-4 border border-[--border-soft] rounded-xl p-4 bg-[--bg-elev-1] space-y-3"
      >
        <h3 class="text-sm font-semibold text-[--fg-1]">Connect your Anthropic account</h3>

        <!-- Starting spinner -->
        <div v-if="modalPhase === 'starting'" class="flex items-center gap-2 text-sm text-[--fg-3]">
          <span class="inline-block w-4 h-4 border-2 border-[--border-1] border-t-[--fg-1] rounded-full animate-spin"></span>
          <span>Starting connection...</span>
          <button @click="handleCancel" class="ml-auto text-xs text-[--fg-4] hover:text-[--fg-2] transition-colors" data-testid="anthropic-cancel-starting">Cancel</button>
        </div>

        <!-- Awaiting code phase -->
        <template v-if="modalPhase === 'awaiting_code' || modalPhase === 'completing'">
          <ol class="text-xs text-[--fg-3] space-y-1 list-decimal list-inside">
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
              class="text-xs text-[--accent] hover:opacity-80 underline truncate max-w-xs"
            >
              {{ store.anthropicAuthUrl }}
            </a>
            <button
              data-testid="anthropic-copy-url"
              @click="copyUrl"
              class="text-xs text-[--fg-3] hover:text-[--fg-1] border border-[--border-1] hover:border-[--border-2] rounded px-2 py-1 transition-colors flex-shrink-0"
            >
              {{ copied ? 'Copied!' : 'Copy URL' }}
            </button>
          </div>

          <!-- Error from store (inline, shown in awaiting_code) -->
          <p v-if="store.anthropicError" class="text-xs text-[--status-block-fg]">
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
              class="flex-1 bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5] disabled:opacity-50"
              @keydown.enter="handleSubmit"
            />
            <button
              data-testid="anthropic-submit"
              :disabled="!codeInput.trim() || modalPhase === 'completing'"
              @click="handleSubmit"
              class="text-sm bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] font-medium rounded-lg px-3 py-2 transition-colors flex-shrink-0"
            >
              {{ modalPhase === 'completing' ? '…' : 'Submit' }}
            </button>
          </div>

          <!-- Cancel -->
          <button
            @click="handleCancel"
            :disabled="modalPhase === 'completing'"
            class="text-xs text-[--fg-4] hover:text-[--fg-2] disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
        </template>

        <!-- Error phase (start failed) -->
        <template v-if="modalPhase === 'error'">
          <p class="text-xs text-[--status-block-fg]">
            {{ store.anthropicError ?? 'Failed to start connection. Please try again.' }}
          </p>
          <div class="flex gap-2">
            <button
              data-testid="anthropic-retry"
              @click="handleConnect"
              class="text-xs bg-[--accent] hover:opacity-90 text-[--accent-fg] rounded-lg px-3 py-1.5 transition-colors"
            >
              Retry
            </button>
            <button
              @click="handleCancel"
              class="text-xs text-[--fg-4] hover:text-[--fg-2] transition-colors"
            >
              Cancel
            </button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
