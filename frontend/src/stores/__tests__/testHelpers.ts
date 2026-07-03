import { vi } from 'vitest'
import type { BotTransport } from '../../composables/useBotTransport'
import type { WsIncomingEvent } from '../../types/chat'

export function makeTransport(
  events: WsIncomingEvent[],
  opts?: { sendRaw?: (_msg: object) => void },
): BotTransport {
  return {
    async *send(_text: string, _agentVersion: string, _conversationId?: string) {
      for (const event of events) {
        yield event
      }
    },
    onHeartbeat(cb) {
      cb(true)
      return () => {}
    },
    close: vi.fn(),
    sendRaw: opts?.sendRaw ?? vi.fn(),
  }
}

/** Build a standard reply as two events: delta + turn_complete */
export function makeReplyEvents(text: string, sessionId = 'test-session'): WsIncomingEvent[] {
  return [
    { type: 'agent_text_delta', session_id: sessionId, delta: text },
    { type: 'turn_complete', session_id: sessionId, final_text: text },
  ]
}
