import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useChatStore } from '../chat'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from './testHelpers'
import type { WsIncomingEvent } from '../../types/chat'

describe('useChatStore — activeActions & currentPhase', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport([]))
  })

  it('activeActions map is empty initially', () => {
    const store = useChatStore()
    expect(store.activeActions.size).toBe(0)
  })

  it('activeActions is updated when agent_action events arrive (starting)', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'reason', friendly_text: 'Thinking', status: 'starting' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    // After turn_complete activeActions is cleared
    expect(store.activeActions.size).toBe(0)
  })

  it('activeActions holds all actions during streaming', async () => {
    let capturedSize = -1
    const events: WsIncomingEvent[] = [
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'reason', friendly_text: 'Thinking', status: 'starting' },
      { type: 'agent_action', session_id: 'test', id: 'act2', tool_name: 'bash', friendly_text: 'Running bash', status: 'running' },
    ]
    // Use a transport that lets us capture mid-stream state
    const transport = makeTransport([
      ...events,
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ])
    const origSend = transport.send.bind(transport)
    transport.send = async function* (text: string, av: string) {
      for await (const event of origSend(text, av)) {
        yield event
        if (event.type === 'agent_action' && event.id === 'act2') {
          // Capture size after second action
          capturedSize = store.activeActions.size
        }
      }
    }
    setBotTransport(transport)
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(capturedSize).toBe(2)
  })

  it('activeActions entries have correct shape', async () => {
    let capturedAction: unknown = null
    const transport = makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'reason', friendly_text: 'Thinking', status: 'starting' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ])
    const origSend = transport.send.bind(transport)
    transport.send = async function* (text: string, av: string) {
      for await (const event of origSend(text, av)) {
        yield event
        if (event.type === 'agent_action') {
          capturedAction = store.activeActions.get('act1')
        }
      }
    }
    setBotTransport(transport)
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(capturedAction).toMatchObject({
      id: 'act1',
      tool_name: 'reason',
      friendly_text: 'Thinking',
      status: 'starting',
    })
  })

  it('activeActions upserts on same id (status transition)', async () => {
    let capturedAfterComplete: unknown = null
    const transport = makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'reason', friendly_text: 'Thinking', status: 'starting' },
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'reason', friendly_text: 'Thinking', status: 'complete' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ])
    const origSend = transport.send.bind(transport)
    let eventCount = 0
    transport.send = async function* (text: string, av: string) {
      for await (const event of origSend(text, av)) {
        yield event
        if (event.type === 'agent_action' && ++eventCount === 2) {
          // After second agent_action (complete), map should still have 1 entry
          capturedAfterComplete = store.activeActions.get('act1')
        }
      }
    }
    setBotTransport(transport)
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect((capturedAfterComplete as { status: string })?.status).toBe('complete')
  })

  it('activeActions is cleared on turn_complete', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'r', friendly_text: 'X', status: 'running' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.activeActions.size).toBe(0)
  })

  it('activeActions is cleared on session_ended', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'r', friendly_text: 'X', status: 'running' },
      { type: 'session_ended', session_id: 'test' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.activeActions.size).toBe(0)
  })

  it('activeActions is cleared on interrupted', async () => {
    setBotTransport(makeTransport([
      { type: 'agent_action', session_id: 'test', id: 'act1', tool_name: 'r', friendly_text: 'X', status: 'running' },
      { type: 'interrupted', session_id: 'test' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.activeActions.size).toBe(0)
  })

  it('currentPhase is null initially', () => {
    const store = useChatStore()
    expect(store.currentPhase).toBeNull()
  })

  it('currentPhase is set from status events', async () => {
    let capturedPhase: string | null = null
    const transport = makeTransport([
      { type: 'status', session_id: 'test', phase: 'main_reasoning', text: 'Thinking...' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ])
    const origSend = transport.send.bind(transport)
    transport.send = async function* (text: string, av: string) {
      for await (const event of origSend(text, av)) {
        yield event
        if (event.type === 'status') {
          capturedPhase = store.currentPhase
        }
      }
    }
    setBotTransport(transport)
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(capturedPhase).toBe('main_reasoning')
  })

  it('currentPhase is cleared on turn_complete', async () => {
    setBotTransport(makeTransport([
      { type: 'status', session_id: 'test', phase: 'classifier', text: 'Classifying' },
      { type: 'turn_complete', session_id: 'test', final_text: 'done' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.currentPhase).toBeNull()
  })

  it('currentPhase is cleared on session_ended', async () => {
    setBotTransport(makeTransport([
      { type: 'status', session_id: 'test', phase: 'tool_call', text: 'Using tools' },
      { type: 'session_ended', session_id: 'test' },
    ]))
    setActivePinia(createPinia())
    const store = useChatStore()
    await store.send('hi')
    expect(store.currentPhase).toBeNull()
  })

  it('respondToPermission sends decision: approve when approve=true', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
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

  it('respondToPermission sends decision: deny when approve=false', () => {
    const sendRaw = vi.fn()
    setBotTransport(makeTransport([], { sendRaw }))
    setActivePinia(createPinia())
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'destructive',
      target: 'Test',
      reason_from_bot: null,
    }
    store.respondToPermission('req1', false)
    expect(sendRaw).toHaveBeenCalledWith({
      type: 'permission_response',
      request_id: 'req1',
      decision: 'deny',
    })
  })
})
