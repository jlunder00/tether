import type { Ref } from 'vue'

export type AdvanceDirection = 'prev' | 'next'

export interface DragEdgeScrollOptions {
  /** px from the left/right edge to trigger a dwell timer (default: 80) */
  threshold?: number
  /** ms to hold at the edge before firing onAdvance (default: 600) */
  dwell?: number
}

/**
 * Composable that fires onAdvance('prev'|'next') after a dwell period when
 * a drag cursor is within `threshold` pixels of the left or right edge of
 * the given container. Clears the timer on dragleave or dragend.
 *
 * Returns `{ onDragOver, onDragLeave, onDragEnd }` handlers to wire into
 * the container element template — mirrors the pattern in useAutoScrollDrag.
 */
export function useDragEdgeScroll(
  containerRef: Ref<HTMLElement | null>,
  onAdvance: (direction: AdvanceDirection) => void,
  options?: DragEdgeScrollOptions,
) {
  const threshold = options?.threshold ?? 80
  const dwell = options?.dwell ?? 600

  let timer: ReturnType<typeof setTimeout> | null = null

  function clearTimer() {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  function startTimer(direction: AdvanceDirection) {
    if (timer !== null) return // already running — don't reset, keep original dwell
    timer = setTimeout(() => {
      timer = null
      onAdvance(direction)
    }, dwell)
  }

  function onDragOver(e: DragEvent) {
    const container = containerRef.value
    if (!container) return

    const rect = container.getBoundingClientRect()
    const x = e.clientX

    if (x - rect.left < threshold) {
      startTimer('prev')
    } else if (rect.right - x < threshold) {
      startTimer('next')
    } else {
      // Cursor moved out of edge zone during dragover — clear pending timer
      clearTimer()
    }
  }

  function onDragLeave() {
    clearTimer()
  }

  function onDragEnd() {
    clearTimer()
  }

  return { onDragOver, onDragLeave, onDragEnd }
}
