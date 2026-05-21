import { ref } from 'vue'
import { getBotTransport } from './useBotTransport'
import { useAgentPickerStore } from '../stores/agentPicker'

export function useConversationChat(_conversationId: string) {
  const isStreaming = ref(false)
  const streamingContent = ref('')

  async function send(text: string, onChunk: (chunk: string) => void): Promise<void> {
    isStreaming.value = true
    streamingContent.value = ''
    try {
      const agentVersion = useAgentPickerStore().selectedAgent
      for await (const event of getBotTransport().send(text, agentVersion)) {
        if (event.type === 'agent_text_delta') {
          streamingContent.value += event.delta
          onChunk(event.delta)
        } else if (event.type === 'turn_complete') {
          // Final text already accumulated via deltas; nothing extra needed
        }
        // Other event types (agent_action, permission_request, status, etc.)
        // are handled by picker-builder's full composable — ignored here in stub.
      }
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
    }
  }

  function interrupt(): void {
    // stub — full interrupt wired in picker-builder's implementation
  }

  return { isStreaming, streamingContent, send, interrupt }
}
