// Stub interface — will be replaced by picker-builder's implementation
// after feature/chat-permission-and-interrupt-ui lands.
import { ref } from 'vue'
import { getBotTransport } from './useBotTransport'
import { useAgentPickerStore } from '../stores/agentPicker'

export interface ConversationChatState {
  isStreaming: boolean
  streamingContent: string
}

export function useConversationChat(_conversationId: string) {
  const isStreaming = ref(false)
  const streamingContent = ref('')

  async function send(text: string, onChunk: (chunk: string) => void): Promise<void> {
    isStreaming.value = true
    streamingContent.value = ''
    try {
      const agentVersion = useAgentPickerStore().selectedAgent
      for await (const chunk of getBotTransport().send(text, agentVersion)) {
        streamingContent.value += chunk
        onChunk(chunk)
      }
    } finally {
      isStreaming.value = false
      streamingContent.value = ''
    }
  }

  function interrupt(): void {
    // stub — picker-builder will wire this to WS interrupt message
  }

  return { isStreaming, streamingContent, send, interrupt }
}
