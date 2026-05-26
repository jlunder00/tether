<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useAgentPickerStore } from '../stores/agentPicker'
import { useAuthStore } from '../stores/auth'
import type { AgentVersion } from '../stores/agentPicker'

const store = useAgentPickerStore()
const authStore = useAuthStore()
const open = ref(false)
const rootEl = ref<HTMLDivElement | null>(null)

// Premium users bypass trial counter and BYOK modal entirely.
const isPremium = computed(() => authStore.user?.is_paid ?? false)

// Live trial count from WS events; null until first event arrives (show fallback).
const trialRemaining = computed(() => store.trialMessagesRemaining ?? 10)

// True when current provider leaks 2.5 internals — 2.5 shown as unavailable.
const providerIsLeaky = computed(() => store.isLeakyProvider)

// True when free user has exhausted their monthly 2.5 trial quota.
const trialExhausted = computed(
  () => !isPremium.value && store.trialMessagesRemaining === 0,
)

const AGENTS: Array<{ id: AgentVersion; label: string; sublabel: string }> = [
  { id: 'tether-agent-1.0', label: 'tether-agent-1.0', sublabel: 'Classic · free' },
  { id: 'tether-agent-2.0', label: 'tether-agent-2.0', sublabel: 'Modern · free' },
  { id: 'tether-agent-2.5', label: 'tether-agent-2.5', sublabel: 'Premium' },
]

/**
 * Whether the 2.5 option is locked (unselectable).
 * Locks when: provider is leaky, OR trial is exhausted.
 * Premium users are never locked.
 */
function is25Locked(id: AgentVersion): boolean {
  if (id !== 'tether-agent-2.5') return false
  if (isPremium.value) return false
  return providerIsLeaky.value || trialExhausted.value
}

function toggleOpen() {
  open.value = !open.value
}

async function select(version: AgentVersion) {
  if (is25Locked(version)) return // silently ignore clicks on locked option
  open.value = false
  await store.setAgent(version)
}

// Close dropdown when clicking outside the component's root.
function onDocumentClick(e: MouseEvent) {
  if (rootEl.value && !rootEl.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))
</script>

<template>
  <div ref="rootEl" class="relative">
    <!-- Trigger button -->
    <button
      type="button"
      class="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-[--bg-elev-2] text-[--fg-3] hover:bg-[--bg-elev-3] hover:text-[--fg-1] transition-colors border border-[--border-1]"
      @click="toggleOpen"
    >
      <span>{{ store.selectedAgent }}</span>
      <svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- Dropdown -->
    <div
      v-if="open"
      class="absolute bottom-full left-0 mb-1 z-50 min-w-[220px] rounded-lg border border-[--border-1] bg-[--bg-elev-2] shadow-lg py-1"
    >
      <button
        v-for="agent in AGENTS"
        :key="agent.id"
        type="button"
        :data-agent="agent.id"
        :disabled="is25Locked(agent.id)"
        class="w-full flex items-center justify-between px-3 py-2 text-xs text-left transition-colors"
        :class="[
          is25Locked(agent.id)
            ? 'opacity-50 cursor-not-allowed'
            : 'hover:bg-[--bg-elev-3]',
          store.selectedAgent === agent.id ? 'text-[--fg-1]' : 'text-[--fg-3]',
        ]"
        @click="select(agent.id)"
      >
        <span class="flex flex-col gap-0.5 flex-1 min-w-0">
          <span class="flex items-center gap-2">
            <!-- Active checkmark -->
            <svg
              v-if="store.selectedAgent === agent.id"
              class="w-3 h-3 text-[--accent] flex-shrink-0"
              fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <span v-else class="w-3 h-3 flex-shrink-0" />

            <span>
              <span class="font-medium">{{ agent.label }}</span>
              <span v-if="!providerIsLeaky || agent.id !== 'tether-agent-2.5'" class="ml-1 text-[--fg-4]">
                · {{ agent.sublabel }}
              </span>

              <!-- Trial badge for 2.5 — hidden for premium users and leaky-provider users -->
              <span
                v-if="agent.id === 'tether-agent-2.5' && !isPremium && !providerIsLeaky"
                class="ml-1 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-[--accent-veil] text-[--accent]"
              >
                trial: {{ trialRemaining }} left
              </span>
            </span>
          </span>

          <!-- Leaky-provider explanation line -->
          <span
            v-if="agent.id === 'tether-agent-2.5' && providerIsLeaky && !isPremium"
            class="ml-5 text-[--fg-5] text-[10px] leading-tight"
          >
            Unavailable on current provider · Switch to Anthropic to use this model
          </span>

          <!-- Trial exhausted explanation line -->
          <span
            v-else-if="agent.id === 'tether-agent-2.5' && trialExhausted"
            class="ml-5 text-[--fg-5] text-[10px] leading-tight"
          >
            Upgrade to continue
          </span>
        </span>

        <!-- Tooltip for 2.5 (hidden when leaky/exhausted — explanation is inline) -->
        <span
          v-if="agent.id === 'tether-agent-2.5' && !providerIsLeaky && !trialExhausted"
          class="ml-2 text-[--fg-5] cursor-help text-[10px] flex-shrink-0"
          :title="'tether-agent-2.5 uses more advanced models (Sonnet) for the main reasoning steps. On bring-your-own-key plans, this consumes your monthly quota faster than 2.0 (~3-5× tokens per message vs 2.0).'"
        >
          ⓘ
        </span>
      </button>
    </div>

    <!-- BYOK first-use modal -->
    <Teleport to="body">
      <div
        v-if="store.showByokModal"
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/40"
      >
        <div class="bg-[--bg-elev-2] border border-[--border-1] rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4">
          <h3 class="text-sm font-semibold text-[--fg-1] mb-2">Switch to tether-agent-2.5?</h3>
          <p class="text-xs text-[--fg-3] mb-5 leading-relaxed">
            tether-agent-2.5 is the premium model. On bring-your-own-key plans, it uses
            ~3–5× more of your Anthropic quota per message compared to 2.0.
          </p>
          <div class="flex gap-2 justify-end">
            <button
              type="button"
              class="text-xs px-3 py-1.5 rounded-lg bg-[--bg-elev-3] text-[--fg-2] hover:bg-[--bg-elev-4] transition-colors"
              @click="store.cancelByokModal()"
            >
              Stay on 2.0
            </button>
            <button
              type="button"
              class="text-xs px-3 py-1.5 rounded-lg bg-[--accent] text-white hover:opacity-90 transition-opacity"
              @click="store.confirmByokModal()"
            >
              Continue
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
