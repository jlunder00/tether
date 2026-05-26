import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'
import { useAuthStore } from './auth'
import { isLeakyProvider as checkLeaky, DEFAULT_PROVIDER } from '../constants/agentProvider'

const AGENT_VERSIONS = ['tether-agent-1.0', 'tether-agent-2.0', 'tether-agent-2.5'] as const
export type AgentVersion = (typeof AGENT_VERSIONS)[number]

const DEFAULT_AGENT: AgentVersion = 'tether-agent-2.0'
const SETTING_KEY = 'preferred_agent_version'

function isValidAgent(v: unknown): v is AgentVersion {
  return typeof v === 'string' && (AGENT_VERSIONS as readonly string[]).includes(v)
}

export const useAgentPickerStore = defineStore('agentPicker', () => {
  const selectedAgent = ref<AgentVersion>(DEFAULT_AGENT)
  const showByokModal = ref(false)
  // Holds the pending 2.5 selection while the BYOK modal awaits confirmation.
  const pendingAgent = ref<AgentVersion | null>(null)

  // Trial counter: null = not yet received from server (show default); 0 = exhausted.
  const trialMessagesRemaining = ref<number | null>(null)

  // Provider: defaults to anthropic_oauth (safe). Set from user settings when available.
  const currentProvider = ref<string>(DEFAULT_PROVIDER)

  // True when the current provider leaks premium 2.5 internals.
  const isLeakyProvider = computed(() => checkLeaky(currentProvider.value))

  /** Called by chat store when a trial_usage_update WS event arrives. */
  function setTrialRemaining(remaining: number): void {
    trialMessagesRemaining.value = remaining
  }

  async function fetchPreference(): Promise<void> {
    try {
      const resp = await api('/api/settings')
      if (!resp.ok) return
      const data = await resp.json()
      const val = data[SETTING_KEY]
      if (isValidAgent(val)) {
        selectedAgent.value = val
      }
      // Load provider if present (future: user sets this in settings)
      if (typeof data.current_provider === 'string') {
        currentProvider.value = data.current_provider
      }
    } catch {
      // Network failure — keep default
    }
  }

  /** Persist a version to the backend and update selectedAgent; rollback on failure. */
  async function _commitAgent(version: AgentVersion): Promise<void> {
    const previous = selectedAgent.value
    selectedAgent.value = version
    try {
      const resp = await api(`/api/settings/${SETTING_KEY}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: version }),
      })
      if (!resp.ok) {
        selectedAgent.value = previous
      }
    } catch {
      selectedAgent.value = previous
    }
  }

  /**
   * Select an agent version.
   *
   * For tether-agent-2.5 on leaky providers: silently blocked — provider
   * cannot run 2.5 due to IP-leakage policy. Picker handles the UI state.
   *
   * For tether-agent-2.5 on free users (safe provider): opens the BYOK
   * confirmation modal WITHOUT committing. The selection is only persisted
   * after confirmByokModal().
   *
   * For premium users (is_paid) or any other version: commits immediately.
   */
  async function setAgent(version: AgentVersion): Promise<void> {
    // Leaky provider gate — silently block 2.5 regardless of tier.
    if (version === 'tether-agent-2.5' && isLeakyProvider.value) return

    const isPremium = useAuthStore().user?.is_paid ?? false

    if (version === 'tether-agent-2.5' && !isPremium) {
      pendingAgent.value = version
      showByokModal.value = true
      return // wait for confirmByokModal() or cancelByokModal()
    }

    await _commitAgent(version)
  }

  /** User clicked "Continue" in the BYOK modal — commit the pending selection. */
  async function confirmByokModal(): Promise<void> {
    const version = pendingAgent.value
    pendingAgent.value = null
    showByokModal.value = false
    if (version) await _commitAgent(version)
  }

  /** User clicked "Stay on 2.0" — discard the pending selection, close modal. */
  function cancelByokModal(): void {
    pendingAgent.value = null
    showByokModal.value = false
  }

  return {
    selectedAgent,
    showByokModal,
    pendingAgent,
    trialMessagesRemaining,
    currentProvider,
    isLeakyProvider,
    setTrialRemaining,
    fetchPreference,
    setAgent,
    confirmByokModal,
    cancelByokModal,
  }
})
