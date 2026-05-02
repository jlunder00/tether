import { ref } from 'vue'
import type { DraggableTaskPayload } from './useDraggableTask'

export type DropPayload = DraggableTaskPayload | Record<string, unknown>

export interface UseDropZoneOptions<TContext = unknown> {
  /** Called when a valid payload is dropped. Semantics are handled by the caller. */
  onDrop: (payload: DropPayload, targetContext: TContext | undefined) => void
  /** Arbitrary context passed through to onDrop — e.g. { anchorId, date } */
  targetContext?: TContext
}

/**
 * Unified HTML5 DnD drop-target composable.
 *
 * Absorbs the `dragEnterCount` counter pattern (prevents isOver flicker when
 * cursor moves over child elements) used in KanbanColumn.
 *
 * Returns:
 * - `isOver` — true while a drag is over the drop zone; bind for visual feedback
 * - `dropHandlers` — attach to the container element
 *
 * @param options.onDrop  Called with (parsedPayload, targetContext) on valid drop
 * @param options.targetContext  Forwarded as-is to onDrop (anchor id, date, etc.)
 */
export function useDropZone<TContext = unknown>(options: UseDropZoneOptions<TContext>) {
  const isOver = ref(false)
  // Counter tracks nested dragenter/dragleave so child elements don't flicker isOver
  let enterCount = 0

  // onDragEnter fires ONCE per element entered — use it for the counter.
  // onDragOver fires continuously (~60fps) — only preventDefault + dropEffect here.
  function onDragEnter(evt: DragEvent) {
    evt.preventDefault()
    enterCount++
    isOver.value = true
  }

  function onDragOver(evt: DragEvent) {
    evt.preventDefault()
    if (evt.dataTransfer) evt.dataTransfer.dropEffect = 'move'
  }

  function onDragLeave() {
    enterCount = Math.max(0, enterCount - 1)
    if (enterCount === 0) isOver.value = false
  }

  function onDrop(evt: DragEvent) {
    evt.preventDefault()
    enterCount = 0
    isOver.value = false

    const raw = evt.dataTransfer?.getData('text/plain')
    if (!raw) return

    let payload: DropPayload
    try {
      payload = JSON.parse(raw)
    } catch {
      return // ignore malformed data from other drag sources
    }

    options.onDrop(payload, options.targetContext)
  }

  return {
    isOver,
    dropHandlers: { onDragEnter, onDragOver, onDragLeave, onDrop },
  }
}
