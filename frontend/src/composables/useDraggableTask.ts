import { ref } from 'vue'
import type { Ref } from 'vue'
import type { Task } from '../stores/plan'

/**
 * Superset drag payload written to `text/plain` on dragstart.
 * All fields from all drag contexts are present so any drop target can
 * read what it needs without knowing the source view.
 */
export interface DraggableTaskPayload {
  type: 'task'
  taskId: string
  title: string
  /** Anchor the task came from (plan view day/week) */
  fromAnchorId?: string
  /** Date string (YYYY-MM-DD) the task came from */
  fromDate?: string
  /** ISO start time when task has a calendar event */
  fromStartTime?: string
  /** Duration in ms when task has a calendar event */
  durationMs?: number
}

/** Optional context provided by the parent to enrich the drag payload */
export interface DraggableTaskContext {
  fromAnchorId?: string
  fromDate?: string
  fromStartTime?: string
  durationMs?: number
}

/**
 * Unified HTML5 DnD drag-source composable for task cards.
 *
 * Returns:
 * - `isDragging` — true while the card is being dragged; bind to
 *   `v-show="!isDragging"` on the source element to hide it on pickup
 * - `dragHandlers` — attach to the draggable element's @dragstart / @dragend
 *
 * @param taskRef  Reactive ref to the task being dragged
 * @param contextRef  Optional reactive context (anchor, date, calendar fields)
 */
export function useDraggableTask(
  taskRef: Ref<Task>,
  contextRef?: Ref<DraggableTaskContext | undefined>,
) {
  const isDragging = ref(false)

  function onDragStart(evt: DragEvent) {
    const task = taskRef.value
    if (!task.id) {
      evt.preventDefault()
      return
    }
    if (!evt.dataTransfer) return

    const ctx = contextRef?.value
    const payload: DraggableTaskPayload = {
      type: 'task',
      taskId: task.id,
      title: task.text,
      ...(ctx?.fromAnchorId !== undefined && { fromAnchorId: ctx.fromAnchorId }),
      ...(ctx?.fromDate !== undefined && { fromDate: ctx.fromDate }),
      ...(ctx?.fromStartTime !== undefined && { fromStartTime: ctx.fromStartTime }),
      ...(ctx?.durationMs !== undefined && { durationMs: ctx.durationMs }),
    }

    evt.dataTransfer.effectAllowed = 'move'
    evt.dataTransfer.setData('text/plain', JSON.stringify(payload))
    // Defer source-hiding to rAF so the browser can capture a visible ghost image
    // before display:none is applied. Setting isDragging synchronously causes Vue's
    // microtask DOM update to hide the element before Chrome snapshots the ghost.
    requestAnimationFrame(() => { isDragging.value = true })
  }

  function onDragEnd() {
    isDragging.value = false
  }

  return {
    isDragging,
    dragHandlers: { onDragStart, onDragEnd },
  }
}
