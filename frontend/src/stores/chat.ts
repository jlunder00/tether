import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage } from '../types/chat'
import { getBotTransport } from '../composables/useBotTransport'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const heartbeat = ref(false)

  const transport = getBotTransport()
  transport.onHeartbeat(a => { heartbeat.value = a })

  async function send(text: string): Promise<void> {
    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      ts: Date.now(),
    }
    messages.value.push(userMsg)

    const botMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'bot',
      content: '',
      ts: Date.now(),
    }
    messages.value.push(botMsg)
    isStreaming.value = true

    try {
      for await (const chunk of transport.send(text)) {
        botMsg.content += chunk
      }
    } finally {
      isStreaming.value = false
    }
  }

  return { messages, isStreaming, heartbeat, send }
})
