import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat'
import { setBotTransport } from '../../composables/useBotTransport'
import type { BotTransport } from '../../composables/useBotTransport'

function makeMockTransport(chunks: string[]): BotTransport {
  return {
    async *send(_text: string) {
      for (const chunk of chunks) {
        yield chunk
      }
    },
    onHeartbeat(cb) {
      cb(true)
      return () => {}
    },
    close: vi.fn(),
  }
}

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeMockTransport(['Hello', ', world']))
  })

  it('starts with empty messages', () => {
    const store = useChatStore()
    expect(store.messages).toHaveLength(0)
  })

  it('heartbeat is true after transport fires', () => {
    const store = useChatStore()
    expect(store.heartbeat).toBe(true)
  })

  it('send appends user message immediately', async () => {
    const store = useChatStore()
    const p = store.send('hi')
    expect(store.messages[0]).toMatchObject({ role: 'user', content: 'hi' })
    await p
  })

  it('send appends bot message that accumulates chunks', async () => {
    const store = useChatStore()
    await store.send('hi')
    expect(store.messages).toHaveLength(2)
    const bot = store.messages[1]
    expect(bot.role).toBe('bot')
    expect(bot.content).toBe('Hello, world')
  })

  it('isStreaming is true during send and false after', async () => {
    const store = useChatStore()
    // Replace transport with one that yields a single chunk after a tick
    let resolve!: () => void
    const slowTransport: BotTransport = {
      async *send(_text: string) {
        await new Promise<void>(r => { resolve = r })
        yield 'chunk'
      },
      onHeartbeat(cb) { cb(true); return () => {} },
      close: vi.fn(),
    }
    setBotTransport(slowTransport)
    setActivePinia(createPinia())
    const store2 = useChatStore()

    const p = store2.send('test')
    // isStreaming should flip true immediately
    expect(store2.isStreaming).toBe(true)
    resolve()
    await p
    expect(store2.isStreaming).toBe(false)
  })

  it('bot message has no streaming field', async () => {
    const store = useChatStore()
    await store.send('hi')
    expect(store.messages[1]).not.toHaveProperty('streaming')
  })
})
