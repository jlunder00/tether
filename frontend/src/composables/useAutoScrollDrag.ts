/**
 * Auto-scroll when dragging near viewport edges.
 * Returns a dragover handler to attach to the scroll container
 * and a cleanup function to call on drop.
 *
 * Also usable for kanban columns — attach onDragOver to the column's
 * scroll container and call cleanup() when the drag ends.
 */
export function useAutoScrollDrag(options?: {
  edgeDistance?: number // px from edge to trigger scroll (default: 60)
  scrollSpeed?: number // px per frame (default: 10)
}) {
  const edgeDistance = options?.edgeDistance ?? 60
  const scrollSpeed = options?.scrollSpeed ?? 10

  let rafId: number | null = null
  let currentDirection: -1 | 1 | 0 = 0

  function scrollLoop(direction: -1 | 1) {
    window.scrollBy(0, direction * scrollSpeed)
    rafId = requestAnimationFrame(() => scrollLoop(direction))
  }

  function startScroll(direction: -1 | 1) {
    if (currentDirection === direction) return // already scrolling this way
    stopScroll()
    currentDirection = direction
    scrollLoop(direction)
  }

  function stopScroll() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
    currentDirection = 0
  }

  function onDragOver(evt: DragEvent) {
    const y = evt.clientY
    const viewportHeight = window.innerHeight

    if (y < edgeDistance) {
      startScroll(-1)
    } else if (y > viewportHeight - edgeDistance) {
      startScroll(1)
    } else {
      stopScroll()
    }
  }

  function cleanup() {
    stopScroll()
  }

  return { onDragOver, cleanup }
}
