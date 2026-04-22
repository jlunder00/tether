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
      id: location.protocol === 'https:' ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36),
      role: 'user',
      content: text,
      ts: Date.now(),
    }
    messages.value.push(userMsg)

    const botMsg: ChatMessage = {
      id: location.protocol === 'https:' ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36),
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
