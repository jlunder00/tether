import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from './testHelpers'
import type { WsIncomingEvent } from '../../types/chat'

function makeTextEvents(text: string): WsIncomingEvent[] {
  return [
    { type: 'agent_text_delta', session_id: 'test', delta: text },
    { type: 'turn_complete', session_id: 'test', final_text: text },
  ]
}

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport(makeTextEvents('Hello, world')))
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

  it('send accumulates bot message via agent_text_delta events', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_text_delta', session_id: 'test', delta: 'Hello' },
      { type: 'agent_text_delta', session_id: 'test', delta: ', world' },
      { type: 'turn_complete', session_id: 'test', final_text: 'Hello, world' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.messages).toHaveLength(2)
    const bot = store.messages[1]
    expect(bot.role).toBe('bot')
    expect(bot.content).toBe('Hello, world')
  })

  it('send sets isSessionActive true during send, false after', async () => {
    let resolveEvent!: () => void
    const slowTransport = makeTransport([
      { type: 'agent_text_delta', session_id: 'test', delta: 'chunk' },
      { type: 'turn_complete', session_id: 'test', final_text: 'chunk' },
    ])
    // Wrap send to be async
    const origSend = slowTransport.send.bind(slowTransport)
    slowTransport.send = async function* (text: string, av: string) {
      await new Promise<void>(r => { resolveEvent = r })
      yield* origSend(text, av)
    }
    setBotTransport(slowTransport)
    setActivePinia(createPinia())
    const store = useChatStore()

    const p = store.send('test')
    expect(store.isSessionActive).toBe(true)
    resolveEvent()
    await p
    expect(store.isSessionActive).toBe(false)
  })

  it('isStreaming is true during send and false after', async () => {
    let resolve!: () => void
    const slowTransport = makeTransport([
      { type: 'agent_text_delta', session_id: 'test', delta: 'chunk' },
      { type: 'turn_complete', session_id: 'test', final_text: 'chunk' },
    ])
    const origSend = slowTransport.send.bind(slowTransport)
    slowTransport.send = async function* (text: string, av: string) {
      await new Promise<void>(r => { resolve = r })
      yield* origSend(text, av)
    }
    setBotTransport(slowTransport)
    setActivePinia(createPinia())
    const store = useChatStore()

    const p = store.send('test')
    expect(store.isStreaming).toBe(true)
    resolve()
    await p
    expect(store.isStreaming).toBe(false)
  })

  it('send accumulates agent_action pills on bot message', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'id1', tool_name: 'reason', friendly_text: 'Thinking', status: 'starting' },
      { type: 'agent_action', session_id: 'test', id: 'id2', tool_name: 'bash', friendly_text: 'Running', status: 'starting' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    const bot = store.messages[1]
    expect(bot.actions).toHaveLength(2)
    expect(bot.actions![0]).toMatchObject({ friendly_text: 'Thinking', tool_name: 'reason' })
    expect(bot.actions![1]).toMatchObject({ friendly_text: 'Running', tool_name: 'bash' })
  })

  it('send sets statusMessage from status event, clears on turn_complete', async () => {
    setBotTransport(makeTransport([
      { type: 'status', session_id: 'test', phase: 'main_reasoning', text: 'Thinking...' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    // After turn_complete, statusMessage should be cleared
    expect(store.statusMessage).toBe('')
  })

  it('send sets content = final_text from turn_complete', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_text_delta', session_id: 'test', delta: 'partial' },
      { type: 'turn_complete', session_id: 'test', final_text: 'final answer' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.messages[1].content).toBe('final answer')
  })

  it('session_ended terminates loop and sets isSessionActive false', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_text_delta', session_id: 'test', delta: 'partial' },
      { type: 'session_ended', session_id: 'test' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.isSessionActive).toBe(false)
  })

  it('permission_request sets pendingPermissionRequest', async () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req1',
        kind: 'user_section_edit',
        target: 'Allow file read',
        reason_from_bot: null,
      },
      { type: 'turn_complete', session_id: 'sess1', final_text: '' },
    ], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.pendingPermissionRequest).toMatchObject({
      request_id: 'req1',
      kind: 'user_section_edit',
      target: 'Allow file read',
    })
  })

  it('second permission_request queues behind first', async () => {
    setBotTransport(makeTransport([
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req1',
        kind: 'user_section_edit',
        target: 'First request',
        reason_from_bot: null,
      },
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req2',
        kind: 'destructive',
        target: 'Second request',
        reason_from_bot: null,
      },
      { type: 'turn_complete', session_id: 'sess1', final_text: '' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.pendingPermissionRequest?.request_id).toBe('req1')
    expect(store.permissionQueue).toHaveLength(1)
    expect(store.permissionQueue[0].request_id).toBe('req2')
  })

  it('respondToPermission calls sendRaw with permission_response', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    // Manually set up a pending permission request
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'user_section_edit',
      target: 'Test',
      reason_from_bot: null,
    }
    store.respondToPermission('req1', true)
    expect(sendRaw).toHaveBeenCalledWith({
      type: 'permission_response',
      request_id: 'req1',
      decision: 'approve',
    })
  })

  it('respondToPermission dequeues next from permissionQueue', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    store.pendingPermissionRequest = { request_id: 'req1', kind: 'user_section_edit', target: 'First', reason_from_bot: null }
    store.permissionQueue = [{ request_id: 'req2', kind: 'destructive', target: 'Second', reason_from_bot: null }]
    store.respondToPermission('req1', false)
    expect(store.pendingPermissionRequest?.request_id).toBe('req2')
    expect(store.permissionQueue).toHaveLength(0)
  })

  it('sendInterrupt calls sendRaw with interrupt and activeSessionId', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    store.activeSessionId = 'sess-abc'
    store.sendInterrupt()
    expect(sendRaw).toHaveBeenCalledWith({
      type: 'interrupt',
      session_id: 'sess-abc',
    })
  })

  it('sendInterrupt is no-op when activeSessionId is null', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    store.sendInterrupt()
    expect(sendRaw).not.toHaveBeenCalled()
  })

  it('bot message has no streaming field', async () => {
    const store = useChatStore()
    await store.send('hi')
    expect(store.messages[1]).not.toHaveProperty('streaming')
  })
})

describe('useChatStore — session_timeout handling', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('session_timeout clears pendingPermissionRequest', async () => {
    setBotTransport(makeTransport([
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req1',
        kind: 'user_section_edit',
        target: 'Read file',
        reason_from_bot: null,
      },
      {
        type: 'session_timeout',
        session_id: 'sess1',
        reason: 'permission_timeout',
        request_id: 'req1',
      },
    ]))
    const store = useChatStore()
    await store.send('hi')
    expect(store.pendingPermissionRequest).toBeNull()
  })

  it('session_timeout clears permissionQueue', async () => {
    setBotTransport(makeTransport([
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req1',
        kind: 'user_section_edit',
        target: 'Read file',
        reason_from_bot: null,
      },
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req2',
        kind: 'destructive',
        target: 'Delete thing',
        reason_from_bot: null,
      },
      {
        type: 'session_timeout',
        session_id: 'sess1',
        reason: 'permission_timeout',
        request_id: 'req1',
      },
    ]))
    const store = useChatStore()
    await store.send('hi')
    expect(store.permissionQueue).toHaveLength(0)
  })

  it('session_timeout sets sessionTimedOut true', async () => {
    setBotTransport(makeTransport([
      {
        type: 'session_timeout',
        session_id: 'sess1',
        reason: 'permission_timeout',
        request_id: 'req1',
      },
    ]))
    const store = useChatStore()
    await store.send('hi')
    expect(store.sessionTimedOut).toBe(true)
  })

  it('session_timeout does NOT call sendRaw with a deny', async () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([
      {
        type: 'permission_request',
        session_id: 'sess1',
        request_id: 'req1',
        kind: 'user_section_edit',
        target: 'Read file',
        reason_from_bot: null,
      },
      {
        type: 'session_timeout',
        session_id: 'sess1',
        reason: 'permission_timeout',
        request_id: 'req1',
      },
    ], { sendRaw }))
    const store = useChatStore()
    await store.send('hi')
    // Backend already denied — frontend must NOT send permission_response
    expect(sendRaw).not.toHaveBeenCalled()
  })

  it('send resets sessionTimedOut on new send', async () => {
    setBotTransport(makeTransport([
      {
        type: 'session_timeout',
        session_id: 'sess1',
        reason: 'permission_timeout',
        request_id: 'req1',
      },
    ]))
    const store = useChatStore()
    await store.send('first')

    setBotTransport(makeTransport([
      { type: 'turn_complete', session_id: 'sess1', final_text: 'ok' },
    ]))
    await store.send('second')
    expect(store.sessionTimedOut).toBe(false)
  })
})
