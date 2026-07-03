import { ref } from 'vue'
import { getBotTransport } from './useBotTransport'
import { useAgentPickerStore } from '../stores/agentPicker'

export function useConversationChat(_conversationId: string) {
  const isStreaming = ref(false)
  const streamingContent = ref('')

  async function send(text: string, onChunk: (chunk: string) => void): Promise<string> {
    isStreaming.value = true
    streamingContent.value = ''
    let finalText = ''
    try {
      const agentVersion = useAgentPickerStore().selectedAgent
      for await (const event of getBotTransport().send(text, agentVersion)) {
        if (event.type === 'agent_text_delta') {
          streamingContent.value += event.delta
          onChunk(event.delta)
        } else if (event.type === 'turn_complete') {
          // Capture the authoritative final text from the server. Callers use
          // this as the canonical message body; accumulated delta text is only
          // for progressive display and may be incomplete if the stream drops.
          finalText = event.final_text
        }
        // Other event types (agent_action, permission_request, status, etc.)
        // are handled by picker-builder's full composable — ignored here in stub.
      }
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
    }
    return finalText
  }

  function interrupt(): void {
    // stub — full interrupt wired in picker-builder's implementation
  }

  return { isStreaming, streamingContent, send, interrupt }
}
