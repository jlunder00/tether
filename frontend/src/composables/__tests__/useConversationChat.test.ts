import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { setBotTransport } from '../useBotTransport'
import { makeTransport } from '../../stores/__tests__/testHelpers'
import type { WsIncomingEvent } from '../../types/chat'
import { useConversationChat } from '../useConversationChat'

vi.mock('../../stores/agentPicker', () => ({
  useAgentPickerStore: () => ({ selectedAgent: 'tether-agent-2.0', fetchPreference: vi.fn() }),
}))

describe('useConversationChat', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('send() — forwards conversationId to the transport', () => {
    it('passes the conversationId given to useConversationChat through to transport.send', async () => {
      const sendSpy = vi.fn(async function* () {
        yield { type: 'turn_complete', session_id: 's1', final_text: 'ok' } as WsIncomingEvent
      })
      setBotTransport({
        send: sendSpy,
        onHeartbeat: () => () => {},
        close: vi.fn(),
        sendRaw: vi.fn(),
      })

      const { send } = useConversationChat('conv-scoped-1')
      await send('ping', () => {})

      expect(sendSpy).toHaveBeenCalledWith('ping', 'tether-agent-2.0', 'conv-scoped-1')
    })
  })

  describe('send() — turn_complete.final_text handling', () => {
    it('returns final_text when only turn_complete arrives (no deltas)', async () => {
      // Simulates one_shot / non-streaming responses where the bot sends only
      // turn_complete with the full answer and no preceding agent_text_delta events.
      // Before fix: send() returned void — streamingBubble stayed '' and the
      // message was silently dropped. After fix: send() returns final_text.
      setBotTransport(makeTransport([
        { type: 'turn_complete', session_id: 's1', final_text: 'Hello from server' },
      ]))

      const { send } = useConversationChat('conv-1')
      const chunks: string[] = []
      const finalText = await send('ping', (c) => chunks.push(c))

      expect(finalText).toBe('Hello from server')
      expect(chunks).toHaveLength(0) // no chunks fired — delta path not triggered
    })

    it('returns final_text from turn_complete even when deltas also arrive', async () => {
      // The authoritative text is always turn_complete.final_text.
      // Deltas are for progressive display only — final_text is the canonical record.
      setBotTransport(makeTransport([
        { type: 'agent_text_delta', session_id: 's1', delta: 'Hello ' },
        { type: 'agent_text_delta', session_id: 's1', delta: 'world' },
        { type: 'turn_complete', session_id: 's1', final_text: 'Hello world' },
      ]))

      const { send } = useConversationChat('conv-2')
      const chunks: string[] = []
      const finalText = await send('ping', (c) => chunks.push(c))

      expect(finalText).toBe('Hello world')
      expect(chunks).toEqual(['Hello ', 'world']) // deltas still fire onChunk for streaming display
    })

    it('returns empty string when turn_complete.final_text is empty', async () => {
      // Caller (ConversationView) falls back to accumulated delta text when finalText is ''.
      // This covers future protocol extensions where final_text may be omitted.
      setBotTransport(makeTransport([
        { type: 'agent_text_delta', session_id: 's1', delta: 'streamed text' },
        { type: 'turn_complete', session_id: 's1', final_text: '' },
      ]))

      const { send } = useConversationChat('conv-3')
      const chunks: string[] = []
      const finalText = await send('ping', (c) => chunks.push(c))

      expect(finalText).toBe('')
      expect(chunks).toEqual(['streamed text'])
    })

    it('still calls onChunk for every agent_text_delta (streaming display unaffected)', async () => {
      // Ensure the streaming display path is not broken by the return-type change.
      const events: WsIncomingEvent[] = [
        { type: 'agent_text_delta', session_id: 's1', delta: 'A' },
        { type: 'agent_text_delta', session_id: 's1', delta: 'B' },
        { type: 'agent_text_delta', session_id: 's1', delta: 'C' },
        { type: 'turn_complete', session_id: 's1', final_text: 'ABC' },
      ]
      setBotTransport(makeTransport(events))

      const { send } = useConversationChat('conv-4')
      const onChunk = vi.fn()
      await send('test', onChunk)

      expect(onChunk).toHaveBeenCalledTimes(3)
      expect(onChunk).toHaveBeenNthCalledWith(1, 'A')
      expect(onChunk).toHaveBeenNthCalledWith(2, 'B')
      expect(onChunk).toHaveBeenNthCalledWith(3, 'C')
    })
  })
})
