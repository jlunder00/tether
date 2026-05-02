/**
 * Track 3: KanbanColumn DnD enhancements (test stubs)
 *
 * Tests for:
 *  1. Replace manual dragEnterCount with useDropZone composable
 *  2. Source task card hidden (v-show="!isDragging") during drag
 *  3. API call moved from KanbanView into kanbanStore.moveTaskToColumn action
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { KanbanColumn as KanbanColumnType } from '../../stores/kanban'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
}))

const testColumn: KanbanColumnType = {
  id: 'col_done',
  name: 'Done',
  position: 3,
  color: '#22c55e',
  match_rules: { status: 'done' },
  entry_rules: { set_status: 'done' },
  created_by: null,
}

describe('KanbanColumn — useDropZone migration (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it.todo('isOver from useDropZone applies highlight class when dragging over column body')

  it.todo('isOver resets correctly after dragleave — no flicker on child element transitions')

  it.todo('isOver resets to false after drop')

  it.todo('no manual dragEnterCount ref exists in component (replaced by useDropZone)')
})

describe('KanbanColumn — source task hiding (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it.todo('task card in source column is hidden (v-show=false) while isDragging is true')

  it.todo('task card becomes visible again after dragend')

  it.todo('only the dragged task is hidden — other tasks in same column remain visible')
})
