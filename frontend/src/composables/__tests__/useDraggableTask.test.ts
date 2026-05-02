/**
 * useDraggableTask composable
 *
 * Verifies that:
 *   1. isDragging starts as false
 *   2. onDragStart sets isDragging to true
 *   3. onDragStart writes superset payload to dataTransfer
 *   4. onDragStart with no task id calls preventDefault and does not set isDragging
 *   5. onDragEnd restores isDragging to false
 *   6. Optional context fields (fromAnchorId, fromDate) are included in payload when provided
 *   7. Optional scheduling fields (fromStartTime, durationMs) are included when provided
 *   8. effectAllowed is set to 'move' on dragstart
 */
import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useDraggableTask } from '../useDraggableTask'
import type { Task } from '../../stores/plan'

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    text: 'Test task',
    description: null,
    status: 'pending',
    position: 0,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: null,
    context_node_id: null,
    ...overrides,
  }
}

function makeDragEvent(overrides: Partial<DragEvent> = {}): DragEvent {
  const setData = vi.fn()
  return {
    preventDefault: vi.fn(),
    dataTransfer: {
      setData,
      effectAllowed: '',
    },
    ...overrides,
  } as unknown as DragEvent
}

describe('useDraggableTask', () => {
  it('isDragging starts as false', () => {
    const taskRef = ref(makeTask())
    const { isDragging } = useDraggableTask(taskRef)
    expect(isDragging.value).toBe(false)
  })

  it('onDragStart sets isDragging to true (after rAF fires)', () => {
    const rafCallbacks: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => { rafCallbacks.push(cb); return 0 })
    const taskRef = ref(makeTask())
    const { isDragging, dragHandlers } = useDraggableTask(taskRef)
    dragHandlers.onDragStart(makeDragEvent())
    rafCallbacks.forEach(cb => cb(0))
    expect(isDragging.value).toBe(true)
    vi.restoreAllMocks()
  })

  it('onDragEnd restores isDragging to false', () => {
    const rafCallbacks: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => { rafCallbacks.push(cb); return 0 })
    const taskRef = ref(makeTask())
    const { isDragging, dragHandlers } = useDraggableTask(taskRef)
    dragHandlers.onDragStart(makeDragEvent())
    rafCallbacks.forEach(cb => cb(0))
    expect(isDragging.value).toBe(true)
    dragHandlers.onDragEnd()
    expect(isDragging.value).toBe(false)
    vi.restoreAllMocks()
  })

  it('onDragStart writes type and taskId to dataTransfer', () => {
    const taskRef = ref(makeTask({ id: 'task-abc', text: 'My task' }))
    const { dragHandlers } = useDraggableTask(taskRef)
    const evt = makeDragEvent()
    dragHandlers.onDragStart(evt)
    expect(evt.dataTransfer!.setData).toHaveBeenCalledWith('text/plain', expect.any(String))
    const [, raw] = (evt.dataTransfer!.setData as ReturnType<typeof vi.fn>).mock.calls[0]
    const payload = JSON.parse(raw)
    expect(payload.type).toBe('task')
    expect(payload.taskId).toBe('task-abc')
    expect(payload.title).toBe('My task')
  })

  it('sets effectAllowed to "move"', () => {
    const taskRef = ref(makeTask())
    const { dragHandlers } = useDraggableTask(taskRef)
    const evt = makeDragEvent()
    dragHandlers.onDragStart(evt)
    expect((evt.dataTransfer as DataTransfer).effectAllowed).toBe('move')
  })

  it('includes fromAnchorId and fromDate in payload when context provided', () => {
    const taskRef = ref(makeTask({ id: 't1' }))
    const contextRef = ref({ fromAnchorId: 'anchor-morning', fromDate: '2026-05-02' })
    const { dragHandlers } = useDraggableTask(taskRef, contextRef)
    const evt = makeDragEvent()
    dragHandlers.onDragStart(evt)
    const [, raw] = (evt.dataTransfer!.setData as ReturnType<typeof vi.fn>).mock.calls[0]
    const payload = JSON.parse(raw)
    expect(payload.fromAnchorId).toBe('anchor-morning')
    expect(payload.fromDate).toBe('2026-05-02')
  })

  it('includes fromStartTime and durationMs when provided in context', () => {
    const taskRef = ref(makeTask({ id: 't1' }))
    const contextRef = ref({
      fromAnchorId: 'anchor-focus',
      fromDate: '2026-05-02',
      fromStartTime: '2026-05-02T09:00:00',
      durationMs: 3600000,
    })
    const { dragHandlers } = useDraggableTask(taskRef, contextRef)
    const evt = makeDragEvent()
    dragHandlers.onDragStart(evt)
    const [, raw] = (evt.dataTransfer!.setData as ReturnType<typeof vi.fn>).mock.calls[0]
    const payload = JSON.parse(raw)
    expect(payload.fromStartTime).toBe('2026-05-02T09:00:00')
    expect(payload.durationMs).toBe(3600000)
  })

  it('calls preventDefault and does NOT set isDragging when task has no id', () => {
    const taskRef = ref(makeTask({ id: '' }))
    const { isDragging, dragHandlers } = useDraggableTask(taskRef)
    const evt = makeDragEvent()
    dragHandlers.onDragStart(evt)
    expect(evt.preventDefault).toHaveBeenCalled()
    expect(isDragging.value).toBe(false)
  })

  it('does nothing if dataTransfer is null', () => {
    const taskRef = ref(makeTask())
    const { isDragging, dragHandlers } = useDraggableTask(taskRef)
    const evt = makeDragEvent({ dataTransfer: null as unknown as DataTransfer })
    // Should not throw
    expect(() => dragHandlers.onDragStart(evt)).not.toThrow()
    expect(isDragging.value).toBe(false)
  })

  it('isDragging is NOT set synchronously during onDragStart — deferred via rAF so ghost capture window stays open', () => {
    // HTML5 DnD: browsers capture the ghost image after dragstart handlers complete
    // but before rAF. Setting isDragging=true synchronously causes Vue to apply
    // display:none before the ghost snapshot — resulting in no visible ghost.
    // Fix: wrap the source-hiding assignment in requestAnimationFrame.
    const rafCallbacks: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      rafCallbacks.push(cb)
      return 0
    })

    const taskRef = ref(makeTask())
    const { isDragging, dragHandlers } = useDraggableTask(taskRef)
    dragHandlers.onDragStart(makeDragEvent())

    // Immediately after — isDragging must still be false (browser is capturing ghost here)
    expect(isDragging.value).toBe(false)

    // Fire rAF — source hiding now applies
    rafCallbacks.forEach(cb => cb(0))
    expect(isDragging.value).toBe(true)

    vi.restoreAllMocks()
  })
})
