import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CalendarFilterPanel from '../CalendarFilterPanel.vue'

const MILESTONES = [
  { id: 'm1', context_subject: 'p', name: 'Alpha', description: null, target_date: null, status: 'pending' as const, status_override: false, color: '#f00', created_at: '', updated_at: '', task_count: 0, done_count: 0, task_ids: [], tasks: [] },
  { id: 'm2', context_subject: 'p', name: 'Beta',  description: null, target_date: null, status: 'pending' as const, status_override: false, color: '#0f0', created_at: '', updated_at: '', task_count: 0, done_count: 0, task_ids: [], tasks: [] },
]
const CONTEXT_NODES = [
  { id: 'n1', parent_id: null, name: 'Work', description: null, node_type: 'context' as const, archived: false, target_date: null, status: null, status_override: false, color: '#00f', created_at: '', updated_at: '' },
  { id: 'n2', parent_id: null, name: 'Personal', description: null, node_type: 'context' as const, archived: false, target_date: null, status: null, status_override: false, color: null, created_at: '', updated_at: '' },
]
const KANBAN_COLUMNS = [
  { id: 'k1', name: 'Todo', position: 0, color: null, match_rules: {}, entry_rules: {}, created_by: null },
  { id: 'k2', name: 'Done', position: 1, color: '#888', match_rules: {}, entry_rules: {}, created_by: null },
]
const EMPTY_FILTER = { milestoneIds: new Set<string>(), contextNodeIds: new Set<string>(), kanbanColumnIds: new Set<string>() }

function makeWrapper(overrides = {}) {
  setActivePinia(createPinia())
  return mount(CalendarFilterPanel, {
    props: {
      modelValue: EMPTY_FILTER,
      milestones: MILESTONES,
      contextNodes: CONTEXT_NODES,
      kanbanColumns: KANBAN_COLUMNS,
      ...overrides,
    },
  })
}

describe('CalendarFilterPanel', () => {
  it('renders milestone section with all milestones', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Alpha')
    expect(w.text()).toContain('Beta')
  })

  it('renders context node section', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Work')
    expect(w.text()).toContain('Personal')
  })

  it('renders kanban column section', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Todo')
    expect(w.text()).toContain('Done')
  })

  it('filters items by search query', async () => {
    const w = makeWrapper()
    const search = w.find('[data-testid="filter-search"]')
    await search.setValue('Alpha')
    expect(w.text()).toContain('Alpha')
    expect(w.text()).not.toContain('Beta')
  })

  it('emits update:modelValue with toggled milestone', async () => {
    const w = makeWrapper()
    const btn = w.find('[data-testid="filter-item-milestone-m1"]')
    await btn.trigger('click')
    const emitted = w.emitted('update:modelValue')!
    expect((emitted[0][0] as typeof EMPTY_FILTER).milestoneIds.has('m1')).toBe(true)
  })

  it('collapses milestone section on header click', async () => {
    const w = makeWrapper()
    const header = w.find('[data-testid="filter-group-milestones"]')
    await header.trigger('click')
    expect(w.find('[data-testid="filter-item-milestone-m1"]').exists()).toBe(false)
  })

  it('emits close on Escape key', async () => {
    const w = makeWrapper()
    await w.trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')).toBeTruthy()
  })
})
