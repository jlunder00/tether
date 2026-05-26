import { defineStore } from 'pinia'
import { ref, type Ref } from 'vue'
import { api } from '../lib/api'

/**
 * Stores user-configurable agent behaviour toggles:
 *   - autoApproveUserActions: skip per-tool confirmation for user_action tools
 *   - devModeShowRawTools: show raw tool names alongside friendly phrases in chat
 *
 * Call fetchSettings() once on app init or when the settings page mounts.
 */
export const useAgentSettingsStore = defineStore('agentSettings', () => {
  const autoApproveUserActions = ref(false)
  const devModeShowRawTools = ref(false)

  async function fetchSettings(): Promise<void> {
    try {
      const resp = await api('/api/settings')
      if (!resp.ok) return
      const data = await resp.json()
      if (data.auto_approve_user_actions !== undefined) {
        autoApproveUserActions.value = data.auto_approve_user_actions === 'true'
      }
      if (data.dev_mode_show_raw_tools !== undefined) {
        devModeShowRawTools.value = data.dev_mode_show_raw_tools === 'true'
      }
    } catch {
      // Network failure — keep defaults
    }
  }

  /** Optimistically persist a boolean setting; rollback on failure. */
  async function commitToggle(key: string, target: Ref<boolean>, enabled: boolean): Promise<void> {
    const previous = target.value
    target.value = enabled
    try {
      const resp = await api(`/api/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: String(enabled) }),
      })
      if (!resp.ok) target.value = previous
    } catch {
      target.value = previous
    }
  }

  function setAutoApprove(enabled: boolean): Promise<void> {
    return commitToggle('auto_approve_user_actions', autoApproveUserActions, enabled)
  }

  function setDevMode(enabled: boolean): Promise<void> {
    return commitToggle('dev_mode_show_raw_tools', devModeShowRawTools, enabled)
  }

  return {
    autoApproveUserActions,
    devModeShowRawTools,
    fetchSettings,
    setAutoApprove,
    setDevMode,
  }
})
