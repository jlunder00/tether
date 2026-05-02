/**
 * Track 3: MiniCalendar DnD (test stubs)
 *
 * MiniCalendar.vue is a new plan-view sidebar component showing a compact
 * month grid. Day cells are drop targets (reschedule task to that date).
 * Task items within the calendar are drag sources.
 */
import { describe, it } from 'vitest'

describe('MiniCalendar — day cell drop targets (Track 3)', () => {
  it.todo('each day cell has @dragover and @drop handlers from useDropZone')

  it.todo('dropping a task onto a day cell calls planStore.moveTaskToAnchor with the correct newDate')

  it.todo('dropping preserves anchorId when task already has an anchor')

  it.todo('isOver from useDropZone applies highlight to the hovered day cell')

  it.todo('isOver clears when drag leaves the cell')
})

describe('MiniCalendar — task item drag sources (Track 3)', () => {
  it.todo('task items rendered within a day cell have draggable=true')

  it.todo('dragstart payload includes type:"task", taskId, fromDate, fromAnchorId')

  it.todo('dragged task is hidden (v-show=false) while isDragging is true')

  it.todo('task reappears after dragend')
})

describe('MiniCalendar — rendering', () => {
  it.todo('renders a 6-week grid (42 day cells)')

  it.todo('highlights today\'s date cell')

  it.todo('renders task indicators (counts or dots) on days that have tasks')
})
