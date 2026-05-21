import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import { useAuthStore } from './auth'

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

  async function fetchPreference(): Promise<void> {
    try {
      const resp = await api('/api/settings')
      if (!resp.ok) return
      const data = await resp.json()
      const val = data[SETTING_KEY]
      if (isValidAgent(val)) {
        selectedAgent.value = val
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
   * For tether-agent-2.5 on free users: opens the BYOK confirmation modal
   * WITHOUT committing. The selection is only persisted after confirmByokModal().
   *
   * For premium users (is_paid) or any other version: commits immediately.
   */
  async function setAgent(version: AgentVersion): Promise<void> {
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
    fetchPreference,
    setAgent,
    confirmByokModal,
    cancelByokModal,
  }
})
