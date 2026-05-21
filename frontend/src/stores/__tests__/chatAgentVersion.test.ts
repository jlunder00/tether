/**
 * Tests that chat.send() passes agent_version from the agentPicker store
 * through to the transport.send() call.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from './testHelpers'
import type { WsIncomingEvent } from '../../types/chat'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

describe('chat store — agent_version forwarding', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('passes agent_version from agentPicker store to transport.send', async () => {
    const capturedCalls: Array<[string, string]> = []
    const events: WsIncomingEvent[] = [
      { type: 'agent_text_delta', session_id: 'mock', delta: 'ok' },
      { type: 'turn_complete', session_id: 'mock', final_text: 'ok' },
    ]
    const transport = makeTransport(events)
    const origSend = transport.send.bind(transport)
    transport.send = async function* (text: string, agentVersion: string) {
      capturedCalls.push([text, agentVersion])
      yield* origSend(text, agentVersion)
    }
    setBotTransport(transport)

    const { useAgentPickerStore } = await import('../agentPicker')
    const pickerStore = useAgentPickerStore()
    pickerStore.selectedAgent = 'tether-agent-1.0'

    const { useChatStore } = await import('../chat')
    const chatStore = useChatStore()
    await chatStore.send('hello')

    expect(capturedCalls).toHaveLength(1)
    expect(capturedCalls[0][1]).toBe('tether-agent-1.0')
  })

  it('defaults to tether-agent-2.0 when picker store has default', async () => {
    const capturedCalls: Array<[string, string]> = []
    const events: WsIncomingEvent[] = [
      { type: 'agent_text_delta', session_id: 'mock', delta: 'ok' },
      { type: 'turn_complete', session_id: 'mock', final_text: 'ok' },
    ]
    const transport = makeTransport(events)
    const origSend = transport.send.bind(transport)
    transport.send = async function* (text: string, agentVersion: string) {
      capturedCalls.push([text, agentVersion])
      yield* origSend(text, agentVersion)
    }
    setBotTransport(transport)

    const { useChatStore } = await import('../chat')
    const chatStore = useChatStore()
    await chatStore.send('hello')

    expect(capturedCalls[0][1]).toBe('tether-agent-2.0')
  })
})
