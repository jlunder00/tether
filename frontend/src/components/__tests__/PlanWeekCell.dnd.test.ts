/**
 * Track 3: PlanWeekCell DnD enhancements (test stubs)
 *
 * Tests for:
 *  1. Task items are draggable via useDraggableTask
 *  2. Source task hidden while isDragging
 *  3. Drop zone migrated to useDropZone (handles child-element flicker correctly)
 */
import { describe, it } from 'vitest'

describe('PlanWeekCell — useDraggableTask on task items (Track 3)', () => {
  it.todo('each task item wrapper div has draggable=true and @dragstart from useDraggableTask')

  it.todo('dragstart payload includes type:"task", taskId, fromDate, fromAnchorId')

  it.todo('task item hidden (v-show=false) while isDragging is true')

  it.todo('task item visible again after dragend')
})

describe('PlanWeekCell — useDropZone migration (Track 3)', () => {
  it.todo('useDropZone isOver applies highlight class — replaces manual isDragOver ref')

  it.todo('isOver correctly resets after dragleave through child elements (counter pattern)')

  it.todo('drop still calls planStore.moveTaskToAnchor with correct args')
})
