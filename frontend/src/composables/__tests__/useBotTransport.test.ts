import { describe, it, expect, vi } from 'vitest'
import { createMockTransport, getBotTransport, setBotTransport } from '../useBotTransport'
import type { BotTransport } from '../useBotTransport'
import type { WsIncomingEvent } from '../../types/chat'

describe('createMockTransport', () => {
  it('send yields agent_text_delta then turn_complete', async () => {
    const transport = createMockTransport()
    const events: WsIncomingEvent[] = []
    for await (const event of transport.send('hello', 'tether-agent-2.0')) {
      events.push(event)
    }
    expect(events[0].type).toBe('agent_text_delta')
    expect(events[events.length - 1].type).toBe('turn_complete')
    transport.close()
  })

  it('send yields exactly two events (delta + turn_complete)', async () => {
    const transport = createMockTransport()
    const events: WsIncomingEvent[] = []
    for await (const event of transport.send('test', 'tether-agent-2.0')) {
      events.push(event)
    }
    expect(events).toHaveLength(2)
    transport.close()
  })

  it('delta event contains text with Echo and mocked', async () => {
    const transport = createMockTransport()
    const events: WsIncomingEvent[] = []
    for await (const event of transport.send('hello', 'tether-agent-2.0')) {
      events.push(event)
    }
    const delta = events[0]
    expect(delta.type).toBe('agent_text_delta')
    if (delta.type === 'agent_text_delta') {
      expect(delta.delta).toContain('Echo: hello')
      expect(delta.delta).toContain('mocked')
    }
    transport.close()
  })

  it('sendRaw exists and is callable', () => {
    const transport = createMockTransport()
    expect(typeof transport.sendRaw).toBe('function')
    // should not throw
    transport.sendRaw({ type: 'interrupt', session_id: 'test' })
    transport.close()
  })

  it('onHeartbeat fires cb immediately with true', () => {
    const transport = createMockTransport()
    const cb = vi.fn()
    const unsub = transport.onHeartbeat(cb)
    expect(cb).toHaveBeenCalledWith(true)
    unsub()
    transport.close()
  })

  it('onHeartbeat returns unsubscribe function', () => {
    const transport = createMockTransport()
    const cb = vi.fn()
    const unsub = transport.onHeartbeat(cb)
    unsub()
    // After unsub, the cb should be detached (no further calls)
    transport.close()
    expect(cb).toHaveBeenCalledTimes(1) // only the initial call
  })

  it('close stops interval', () => {
    vi.useFakeTimers()
    const transport = createMockTransport()
    const cb = vi.fn()
    transport.onHeartbeat(cb)
    cb.mockClear()
    transport.close()
    vi.advanceTimersByTime(10000)
    expect(cb).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})

describe('getBotTransport / setBotTransport singleton', () => {
  it('getBotTransport returns same instance on repeated calls', () => {
    const t1 = getBotTransport()
    const t2 = getBotTransport()
    expect(t1).toBe(t2)
    t1.close()
  })

  it('setBotTransport replaces the singleton', () => {
    const newTransport: BotTransport = {
      send: async function* () {},
      onHeartbeat: () => () => {},
      close: vi.fn(),
      sendRaw: vi.fn(),
    }
    setBotTransport(newTransport)
    expect(getBotTransport()).toBe(newTransport)
  })
})
