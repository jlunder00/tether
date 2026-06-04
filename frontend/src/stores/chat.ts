import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage, PermissionRequest } from '../types/chat'
import { getBotTransport } from '../composables/useBotTransport'
import { useAgentPickerStore } from './agentPicker'

function makeId(): string {
  if (location.protocol === 'https:') return crypto.randomUUID()
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const heartbeat = ref(false)
  const activeSessionId = ref<string | null>(null)
  const isSessionActive = ref(false)
  const statusMessage = ref('')
  const pendingPermissionRequest = ref<PermissionRequest | null>(null)
  const permissionQueue = ref<PermissionRequest[]>([])

  // Register heartbeat via a stable wrapper so it always reflects the current
  // transport, even after setBotTransport() replaces it post-auth.
  getBotTransport().onHeartbeat(a => { heartbeat.value = a })

  async function send(text: string): Promise<void> {
    messages.value.push({ id: makeId(), role: 'user', content: text, ts: Date.now() })

    // Record the index before pushing the bot placeholder so we can write
    // chunks through the reactive proxy (messages.value[botMsgIndex]) rather
    // than a plain-object reference that bypasses Vue's Proxy set-trap.
    const botMsgIndex = messages.value.length
    messages.value.push({ id: makeId(), role: 'bot', content: '', ts: Date.now() })

    isStreaming.value = true
    isSessionActive.value = true
    try {
      const agentVersion = useAgentPickerStore().selectedAgent
      for await (const event of getBotTransport().send(text, agentVersion)) {
        switch (event.type) {
          case 'agent_text_delta':
            activeSessionId.value = event.session_id
            messages.value[botMsgIndex].content += event.delta
            break
          case 'agent_action': {
            activeSessionId.value = event.session_id
            const bot = messages.value[botMsgIndex]
            // Only track starting/running pills; complete just clears in-progress.
            // Wave 2 (frontend-events-renderer) will render rich pill UI.
            if (event.status !== 'complete') {
              const existing = (bot.actions ??= []).find(a => a.friendly_text === event.friendly_text)
              if (!existing) {
                bot.actions!.push({ friendly_text: event.friendly_text, tool_name: event.tool_name })
              }
            }
            break
          }
          case 'permission_request': {
            activeSessionId.value = event.session_id
            const req: PermissionRequest = {
              request_id: event.request_id,
              kind: event.kind,
              target: event.target,
              reason_from_bot: event.reason_from_bot,
            }
            if (!pendingPermissionRequest.value) {
              pendingPermissionRequest.value = req
            } else {
              permissionQueue.value.push(req)
            }
            break
          }
          case 'status':
            activeSessionId.value = event.session_id
            statusMessage.value = event.text
            break
          case 'turn_complete':
            // final_text is canonical — overwrite accumulated deltas
            messages.value[botMsgIndex].content = event.final_text
            statusMessage.value = ''
            isSessionActive.value = false
            return
          case 'interrupted':
            // Pool cancelled the stream (e.g. HTTP client disconnect).
            // Clear in-progress indicators; bot message content is preserved.
            statusMessage.value = ''
            isSessionActive.value = false
            return
          case 'session_ended':
            statusMessage.value = ''
            isSessionActive.value = false
            return
          case 'trial_usage_update':
            useAgentPickerStore().setTrialRemaining(event.remaining)
            break
        }
      }
    } finally {
      isStreaming.value = false
      isSessionActive.value = false
    }
  }

  function respondToPermission(requestId: string, approve: boolean): void {
    getBotTransport().sendRaw({ type: 'permission_response', request_id: requestId, approve })
    pendingPermissionRequest.value = permissionQueue.value.shift() ?? null
  }

  function sendInterrupt(): void {
    if (!activeSessionId.value) return
    getBotTransport().sendRaw({ type: 'interrupt', session_id: activeSessionId.value })
  }

  return {
    messages,
    isStreaming,
    heartbeat,
    activeSessionId,
    isSessionActive,
    statusMessage,
    pendingPermissionRequest,
    permissionQueue,
    send,
    respondToPermission,
    sendInterrupt,
  }
})
