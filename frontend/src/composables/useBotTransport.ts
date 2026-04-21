export interface BotTransport {
  /** Send user text; yields content chunks as they arrive. */
  send(text: string): AsyncIterable<string>
  /** Subscribe to heartbeat changes. Returns an unsubscribe fn. */
  onHeartbeat(cb: (alive: boolean) => void): () => void
  /** Close any underlying connection. */
  close(): void
}

export function createMockTransport(): BotTransport {
  async function* send(text: string): AsyncIterable<string> {
    const reply = `Echo: ${text}\n\nThis is a **mocked** response.`
    for (const chunk of reply.match(/.{1,6}/g) ?? []) {
      await new Promise<void>(r => setTimeout(r, 30))
      yield chunk
    }
  }

  let aliveCb: ((a: boolean) => void) | null = null
  const interval = setInterval(() => aliveCb?.(true), 3000)

  return {
    send,
    onHeartbeat(cb) {
      aliveCb = cb
      cb(true)
      return () => { aliveCb = null }
    },
    close() {
      clearInterval(interval)
      aliveCb = null
    },
  }
}

let _transport: BotTransport | null = null

export function getBotTransport(): BotTransport {
  if (!_transport) _transport = createMockTransport()
  return _transport
}

export function setBotTransport(t: BotTransport): void {
  _transport?.close()
  _transport = t
}
