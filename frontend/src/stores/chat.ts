import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage } from '../types/chat'
import { getBotTransport } from '../composables/useBotTransport'

function makeId(): string {
  if (location.protocol === 'https:') return crypto.randomUUID()
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const isStreaming = ref(false)
  const heartbeat = ref(false)

  const transport = getBotTransport()
  transport.onHeartbeat(a => { heartbeat.value = a })

  async function send(text: string): Promise<void> {
    messages.value.push({ id: makeId(), role: 'user', content: text, ts: Date.now() })

    // Record the index before pushing the bot placeholder so we can write
    // chunks through the reactive proxy (messages.value[botMsgIndex]) rather
    // than a plain-object reference that bypasses Vue's Proxy set-trap.
    const botMsgIndex = messages.value.length
    messages.value.push({ id: makeId(), role: 'bot', content: '', ts: Date.now() })

    isStreaming.value = true
    try {
      for await (const chunk of transport.send(text)) {
        messages.value[botMsgIndex].content += chunk
      }
    } finally {
      isStreaming.value = false
    }
  }

  return { messages, isStreaming, heartbeat, send }
})
