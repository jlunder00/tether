import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export type AgentVersion = 'tether-agent-1.0' | 'tether-agent-2.0' | 'tether-agent-2.5'

const DEFAULT_AGENT: AgentVersion = 'tether-agent-2.0'
const SETTING_KEY = 'preferred_agent_version'

function isValidAgent(v: unknown): v is AgentVersion {
  return v === 'tether-agent-1.0' || v === 'tether-agent-2.0' || v === 'tether-agent-2.5'
}

export const useAgentPickerStore = defineStore('agentPicker', () => {
  const selectedAgent = ref<AgentVersion>(DEFAULT_AGENT)
  const showByokModal = ref(false)

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

  async function setAgent(version: AgentVersion): Promise<void> {
    const previous = selectedAgent.value
    selectedAgent.value = version

    if (version === 'tether-agent-2.5') {
      showByokModal.value = true
    }

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

  function dismissByokModal(): void {
    showByokModal.value = false
  }

  return { selectedAgent, showByokModal, fetchPreference, setAgent, dismissByokModal }
})
