/**
 * Track 3: KanbanStore — moveTaskToColumn action (test stubs)
 *
 * The API call currently lives in KanbanView.onTaskDrop. Track 3 moves it
 * into a store action so KanbanColumn never calls api() directly.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) })),
}))

describe('useKanbanStore — moveTaskToColumn action (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it.todo('moveTaskToColumn PATCHes /api/tasks/:id with status from column entry_rules.set_status')

  it.todo('moveTaskToColumn adds plan_date=today when column entry_rules.prompt_schedule is set and task has no plan_date')

  it.todo('moveTaskToColumn sets plan_date=null and anchor_id=null when column entry_rules.unschedule is true')

  it.todo('moveTaskToColumn applies optimistic update before API call')

  it.todo('moveTaskToColumn reverts optimistic update and re-fetches on API error')

  it.todo('moveTaskToColumn is a no-op when patch would be empty (no fields changed)')

  it.todo('moveTaskToColumn guards against invalid status values not in VALID_STATUSES set')

  it.todo('moveTaskToColumn ignores concurrent drops for same taskId (pendingDrops guard)')
})
