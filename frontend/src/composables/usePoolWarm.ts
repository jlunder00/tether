/**
 * usePoolWarm — fires a best-effort pool warm hint to pre-warm a subprocess
 * for the authenticated user when they land on the chat surface.
 *
 * Call once from ChatPageView.vue (or any component that signals chat intent).
 * Also watches the selected agent version and re-hints on change so the correct
 * subprocess configuration is warmed.
 *
 * 500ms debounce prevents spamming the endpoint on rapid picker changes.
 * Failures are silently swallowed — warming is best-effort and must never
 * interfere with the user experience.
 */
import { watch, onMounted, onUnmounted } from 'vue'
import { api } from '../lib/api'
import { useAgentPickerStore } from '../stores/agentPicker'

const DEBOUNCE_MS = 500

export function usePoolWarm(): void {
  const pickerStore = useAgentPickerStore()
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function scheduleHint(): void {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer)
    }
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      _fireHint(pickerStore.selectedAgent)
    }, DEBOUNCE_MS)
  }

  // Fire on mount (user arrived at the chat surface)
  onMounted(() => {
    scheduleHint()
  })

  // Re-fire when the user changes their agent version selection
  const stopWatch = watch(
    () => pickerStore.selectedAgent,
    () => {
      scheduleHint()
    },
  )

  onUnmounted(() => {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    stopWatch()
  })
}

async function _fireHint(agentVersion: string): Promise<void> {
  try {
    await api('/api/internal/pool/warm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_version: agentVersion }),
    })
  } catch {
    // Best-effort — silently ignore network failures
  }
}
