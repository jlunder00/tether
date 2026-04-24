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

  // C1: resolved once the socket is ready; awaited before every send.
  let resolveOpen!: () => void
  let rejectOpen!: (err: Error) => void
  const openPromise = new Promise<void>((resolve, reject) => {
    resolveOpen = resolve
    rejectOpen = reject
  })

  // C2: slot for the currently-awaited recv; reject path lets a closed
  // socket surface an error instead of hanging the `while (true)` loop.
  let pendingResolve: ((val: MessageEvent) => void) | null = null
  let pendingReject: ((err: Error) => void) | null = null
  const incoming: MessageEvent[] = []

  // H2: single heartbeat subscriber, driven by real socket events.
  let heartbeatCb: ((alive: boolean) => void) | null = null

  function failPending(err: Error): void {
    pendingReject?.(err)
    pendingResolve = null
    pendingReject = null
  }

  ws.onopen = () => {
    resolveOpen()
    heartbeatCb?.(true)
  }

  ws.onmessage = (evt) => {
    if (pendingResolve) {
      pendingResolve(evt)
      pendingResolve = null
      pendingReject = null
    } else {
      incoming.push(evt)
    }
  }

  ws.onerror = () => {
    const err = new Error('WebSocket error')
    rejectOpen(err)
    failPending(err)
    heartbeatCb?.(false)
  }

  ws.onclose = () => {
    failPending(new Error('WebSocket closed'))
    heartbeatCb?.(false)
  }

  return {
    async *send(text: string) {
      // C1: don't send until the socket has opened.
      await openPromise

      // H1: take a private snapshot of any buffered messages so concurrent
      // sends don't steal each other's chunks via the shared `incoming` queue.
      const localQueue: MessageEvent[] = incoming.splice(0)

      ws.send(JSON.stringify({ type: 'user', content: text }))

      // C2: each recv registers both resolve and reject, so onerror/onclose
      // can break us out of this loop.
      while (true) {
        const evt: MessageEvent = await new Promise((resolve, reject) => {
          if (localQueue.length) return resolve(localQueue.shift()!)
          if (incoming.length) return resolve(incoming.shift()!)
          pendingResolve = resolve
          pendingReject = reject
        })
        const msg = JSON.parse(evt.data)
        if (msg.type === 'chunk') yield msg.content
        if (msg.type === 'done') return
      }
    },

    onHeartbeat(cb) {
      heartbeatCb = cb
      // Reflect current readyState immediately so subscribers don't wait
      // for the next socket event to see the right status.
      switch (ws.readyState) {
        case WebSocket.OPEN:
          cb(true)
          break
        case WebSocket.CLOSING:
        case WebSocket.CLOSED:
          cb(false)
          break
      }
      return () => { heartbeatCb = null }
    },

    close() {
      ws.close()
    },
  }
}
