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
    yield `Echo: ${text}\n\nThis is a **mocked** response.`
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

export function createWebSocketTransport(): BotTransport {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/api/bot/chat`)

  let resolve: ((val: MessageEvent) => void) | null = null
  const queue: MessageEvent[] = []

  ws.onmessage = (evt) => {
    if (resolve) { resolve(evt); resolve = null }
    else queue.push(evt)
  }

  return {
    async *send(text: string) {
      // 1. send the message
      ws.send(JSON.stringify({ type: 'user', content: text}))

      // 2. wait for chunks until "done"
      while (true) {
        const evt: MessageEvent = await new Promise(r => {
          if (queue.length) r(queue.shift()!)
            else resolve = r
        })
        const msg = JSON.parse(evt.data)
        if (msg.type === 'chunk') yield msg.content
        if (msg.type === 'done') return
      }
    },

    onHeartbeat(cb) {
      // listen for {"type": "heartbeat"}
      // backend doesnt send thi. just call as true immediately
      cb(true)
      return () => {}
    },
    
    close() {
      ws.close()
    }
  }
}
