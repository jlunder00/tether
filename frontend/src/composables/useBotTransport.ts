export interface BotTransport {
  /**
   * Send user text with the selected agent version; yields typed WS events as they arrive.
   * conversationId is optional — when provided it links the 2.0 layer session to that
   * conversation so scope gating can resolve scope_source_node_id from the conversation's
   * context_node_id. Omitting it is fully backwards-compatible.
   */
  send(
    text: string,
    agentVersion: string,
    conversationId?: string,
  ): AsyncIterable<import('../types/chat').WsIncomingEvent>
  /** Send a raw message on the underlying connection (permission_response, interrupt). No-op if closed. */
  sendRaw(msg: object): void
  /** Subscribe to heartbeat changes. Returns an unsubscribe fn. */
  onHeartbeat(cb: (alive: boolean) => void): () => void
  /** Close any underlying connection. */
  close(): void
}

export function createMockTransport(): BotTransport {
  async function* send(text: string, _agentVersion: string, _conversationId?: string) {
    const body = `Echo: ${text}\n\nThis is a **mocked** response.`
    yield { type: 'agent_text_delta' as const, session_id: 'mock', delta: body }
    yield { type: 'turn_complete' as const, session_id: 'mock', final_text: body }
  }

  let aliveCb: ((a: boolean) => void) | null = null
  const interval = setInterval(() => aliveCb?.(true), 3000)

  return {
    send,
    sendRaw(_msg: object) { /* no-op in mock */ },
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
    async *send(text: string, agentVersion: string, conversationId?: string) {
      // C1: don't send until the socket has opened.
      await openPromise

      // H1: take a private snapshot of any buffered messages so concurrent
      // sends don't steal each other's chunks via the shared `incoming` queue.
      const localQueue: MessageEvent[] = incoming.splice(0)

      ws.send(JSON.stringify({
        type: 'user',
        content: text,
        agent_version: agentVersion,
        conversation_id: conversationId ?? null,
      }))

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
        yield msg
        // Terminate the turn on terminal events.
        if (msg.type === 'turn_complete' || msg.type === 'session_ended') return
      }
    },

    sendRaw(msg: object) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
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
