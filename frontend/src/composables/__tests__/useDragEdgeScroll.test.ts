/**
 * useDragEdgeScroll composable
 *
 * Verifies that:
 *   1. onAdvance('next') fires after dwell when cursor is near right edge
 *   2. onAdvance('prev') fires after dwell when cursor is near left edge
 *   3. onAdvance does NOT fire before the dwell time expires
 *   4. onAdvance does NOT fire when onDragLeave is called before dwell
 *   5. onAdvance does NOT fire when onDragEnd is called before dwell
 *   6. Moving cursor out of the edge zone (no dragleave) also clears the timer
 *   7. Timer does not fire twice for a continuous edge dwell
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useDragEdgeScroll } from '../useDragEdgeScroll'

// Container spanning x=0–500
function makeContainer(): HTMLElement {
  const el = document.createElement('div')
  vi.spyOn(el, 'getBoundingClientRect').mockReturnValue({
    left: 0, right: 500, width: 500,
    top: 0, bottom: 200, height: 200,
    x: 0, y: 0,
    toJSON: () => ({}),
  } as DOMRect)
  return el
}

function makeDragEvent(clientX: number): DragEvent {
  return { clientX, preventDefault: vi.fn() } as unknown as DragEvent
}

describe('useDragEdgeScroll', () => {
  beforeEach(() => {
    // Only fake setTimeout/clearTimeout — leave Vitest's own scheduling intact
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })

  afterEach(() => {
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })

  function setup(threshold = 80, dwell = 600) {
    const containerRef = ref<HTMLElement | null>(makeContainer())
    const onAdvance = vi.fn()
    const handlers = useDragEdgeScroll(containerRef, onAdvance, { threshold, dwell })
    return { handlers, onAdvance, containerRef }
  }

  it('fires onAdvance("next") after dwell when cursor is near right edge', () => {
    const { handlers, onAdvance } = setup()
    // clientX=450, right=500, threshold=80 → 500−450=50 < 80 ✓
    handlers.onDragOver(makeDragEvent(450))
    expect(onAdvance).not.toHaveBeenCalled()
    vi.advanceTimersByTime(600)
    expect(onAdvance).toHaveBeenCalledOnce()
    expect(onAdvance).toHaveBeenCalledWith('next')
  })

  it('fires onAdvance("prev") after dwell when cursor is near left edge', () => {
    const { handlers, onAdvance } = setup()
    // clientX=30, left=0, threshold=80 → 30−0=30 < 80 ✓
    handlers.onDragOver(makeDragEvent(30))
    expect(onAdvance).not.toHaveBeenCalled()
    vi.advanceTimersByTime(600)
    expect(onAdvance).toHaveBeenCalledOnce()
    expect(onAdvance).toHaveBeenCalledWith('prev')
  })

  it('does NOT fire onAdvance before the dwell expires', () => {
    const { handlers, onAdvance } = setup()
    handlers.onDragOver(makeDragEvent(450))
    vi.advanceTimersByTime(599)
    expect(onAdvance).not.toHaveBeenCalled()
  })

  it('does NOT fire when onDragLeave is called before dwell', () => {
    const { handlers, onAdvance } = setup()
    handlers.onDragOver(makeDragEvent(450))
    vi.advanceTimersByTime(300)
    handlers.onDragLeave()
    vi.advanceTimersByTime(400)
    expect(onAdvance).not.toHaveBeenCalled()
  })

  it('does NOT fire when onDragEnd is called before dwell', () => {
    const { handlers, onAdvance } = setup()
    handlers.onDragOver(makeDragEvent(450))
    vi.advanceTimersByTime(300)
    handlers.onDragEnd()
    vi.advanceTimersByTime(400)
    expect(onAdvance).not.toHaveBeenCalled()
  })

  it('clears the timer when cursor moves to mid-container (no dragleave)', () => {
    const { handlers, onAdvance } = setup()
    // Start edge dwell
    handlers.onDragOver(makeDragEvent(450))
    vi.advanceTimersByTime(300)
    // Move to middle — x=250, distance to both edges = 250 > 80
    handlers.onDragOver(makeDragEvent(250))
    vi.advanceTimersByTime(400)
    expect(onAdvance).not.toHaveBeenCalled()
  })

  it('fires only once for continuous edge dwell (repeated dragover calls)', () => {
    const { handlers, onAdvance } = setup()
    handlers.onDragOver(makeDragEvent(450))
    handlers.onDragOver(makeDragEvent(455))
    handlers.onDragOver(makeDragEvent(460))
    vi.advanceTimersByTime(600)
    expect(onAdvance).toHaveBeenCalledOnce()
  })

  it('does nothing when containerRef is null', () => {
    const containerRef = ref<HTMLElement | null>(null)
    const onAdvance = vi.fn()
    const handlers = useDragEdgeScroll(containerRef, onAdvance)
    handlers.onDragOver(makeDragEvent(450))
    vi.advanceTimersByTime(600)
    expect(onAdvance).not.toHaveBeenCalled()
  })

  it('accepts custom threshold and dwell options', () => {
    const { handlers, onAdvance } = setup(50, 300)
    // threshold=50: 500-460=40 < 50 ✓
    handlers.onDragOver(makeDragEvent(460))
    vi.advanceTimersByTime(299)
    expect(onAdvance).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(onAdvance).toHaveBeenCalledWith('next')
  })
})
