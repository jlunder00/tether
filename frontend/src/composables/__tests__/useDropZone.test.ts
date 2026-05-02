/**
 * useDropZone composable
 *
 * Verifies that:
 *   1. isOver starts as false
 *   2. onDragOver sets isOver to true and calls preventDefault
 *   3. onDragLeave decrements count; isOver becomes false when count reaches 0
 *   4. Multiple onDragEnter (via onDragOver) require equal onDragLeave calls to clear isOver
 *   5. onDrop calls preventDefault, resets isOver to false, parses payload, calls options.onDrop
 *   6. onDrop with no dataTransfer does nothing (no throw)
 *   7. onDrop with malformed JSON does not call options.onDrop
 *   8. onDrop with empty payload string does not call options.onDrop
 *   9. targetContext is passed through to options.onDrop
 */
import { describe, it, expect, vi } from 'vitest'
import { useDropZone } from '../useDropZone'

function makeDragEvent(rawPayload?: string | null): DragEvent {
  // null explicitly means "no dataTransfer"; undefined (default) → non-null with empty getData
  const dataTransfer = rawPayload === null
    ? null
    : { getData: vi.fn().mockReturnValue(rawPayload ?? ''), dropEffect: '' }
  return {
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer,
  } as unknown as DragEvent
}

describe('useDropZone', () => {
  it('isOver starts as false', () => {
    const { isOver } = useDropZone({ onDrop: vi.fn() })
    expect(isOver.value).toBe(false)
  })

  it('onDragOver sets isOver to true and calls preventDefault', () => {
    const { isOver, dropHandlers } = useDropZone({ onDrop: vi.fn() })
    const evt = makeDragEvent()
    dropHandlers.onDragOver(evt)
    expect(isOver.value).toBe(true)
    expect(evt.preventDefault).toHaveBeenCalled()
  })

  it('onDragLeave sets isOver to false after single enter', () => {
    const { isOver, dropHandlers } = useDropZone({ onDrop: vi.fn() })
    dropHandlers.onDragOver(makeDragEvent())
    expect(isOver.value).toBe(true)
    dropHandlers.onDragLeave()
    expect(isOver.value).toBe(false)
  })

  it('requires matching onDragLeave calls to clear isOver (enter counter pattern)', () => {
    const { isOver, dropHandlers } = useDropZone({ onDrop: vi.fn() })
    // Simulate entering parent then child — 2 enter events
    dropHandlers.onDragOver(makeDragEvent())
    dropHandlers.onDragOver(makeDragEvent())
    dropHandlers.onDragLeave()
    expect(isOver.value).toBe(true)  // still inside, one enter outstanding
    dropHandlers.onDragLeave()
    expect(isOver.value).toBe(false)
  })

  it('onDrop calls preventDefault, resets isOver, parses payload, calls onDrop callback', () => {
    const onDrop = vi.fn()
    const { isOver, dropHandlers } = useDropZone({ onDrop })
    dropHandlers.onDragOver(makeDragEvent())
    const payload = { type: 'task', taskId: 'task-1', title: 'Do thing' }
    const evt = makeDragEvent(JSON.stringify(payload))
    dropHandlers.onDrop(evt)
    expect(evt.preventDefault).toHaveBeenCalled()
    expect(isOver.value).toBe(false)
    expect(onDrop).toHaveBeenCalledWith(payload, undefined)
  })

  it('passes targetContext through to onDrop callback', () => {
    const onDrop = vi.fn()
    const targetContext = { anchorId: 'morning', date: '2026-05-02' }
    const { dropHandlers } = useDropZone({ onDrop, targetContext })
    const payload = { type: 'task', taskId: 't2' }
    dropHandlers.onDrop(makeDragEvent(JSON.stringify(payload)))
    expect(onDrop).toHaveBeenCalledWith(payload, targetContext)
  })

  it('does not call onDrop callback with empty dataTransfer string', () => {
    const onDrop = vi.fn()
    const { dropHandlers } = useDropZone({ onDrop })
    dropHandlers.onDrop(makeDragEvent(''))
    expect(onDrop).not.toHaveBeenCalled()
  })

  it('does not call onDrop callback with malformed JSON', () => {
    const onDrop = vi.fn()
    const { dropHandlers } = useDropZone({ onDrop })
    dropHandlers.onDrop(makeDragEvent('not-json'))
    expect(onDrop).not.toHaveBeenCalled()
  })

  it('does not throw when dataTransfer is null', () => {
    const onDrop = vi.fn()
    const { dropHandlers } = useDropZone({ onDrop })
    expect(() => dropHandlers.onDrop(makeDragEvent(null))).not.toThrow()
    expect(onDrop).not.toHaveBeenCalled()
  })

  it('counter never goes below 0 on extra onDragLeave calls', () => {
    const { isOver, dropHandlers } = useDropZone({ onDrop: vi.fn() })
    dropHandlers.onDragLeave()
    dropHandlers.onDragLeave()
    expect(isOver.value).toBe(false)
  })

  it('sets dropEffect to "move" on dragover when dataTransfer present', () => {
    const { dropHandlers } = useDropZone({ onDrop: vi.fn() })
    const evt = makeDragEvent()
    dropHandlers.onDragOver(evt)
    expect((evt.dataTransfer as DataTransfer).dropEffect).toBe('move')
  })
})
