import { describe, it, expect, vi } from 'vitest'
import { createMockTransport, getBotTransport, setBotTransport } from '../useBotTransport'
import type { BotTransport } from '../useBotTransport'

describe('createMockTransport', () => {
  it('send yields chunks that reassemble to full reply', async () => {
    const transport = createMockTransport()
    const text = 'hello'
    const chunks: string[] = []
    for await (const chunk of transport.send(text, 'tether-agent-2.0')) {
      chunks.push(chunk)
    }
    const full = chunks.join('')
    expect(full).toContain('Echo: hello')
    expect(full).toContain('mocked')
    transport.close()
  })

  it('send yields exactly one chunk (no streaming simulation)', async () => {
    const transport = createMockTransport()
    const chunks: string[] = []
    for await (const chunk of transport.send('test', 'tether-agent-2.0')) {
      chunks.push(chunk)
    }
    expect(chunks).toHaveLength(1)
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
    }
    setBotTransport(newTransport)
    expect(getBotTransport()).toBe(newTransport)
  })
})
