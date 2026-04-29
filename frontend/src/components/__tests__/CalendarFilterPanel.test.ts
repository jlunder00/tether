import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import CalendarFilterPanel from '../CalendarFilterPanel.vue'
import type { ContextNode } from '../../stores/context'
import type { Anchor } from '../../stores/anchors'
import type { KanbanColumn } from '../../stores/kanban'

const ROOT_NODES: ContextNode[] = [
  { id: 'n1', parent_id: null, name: 'Work', description: null, node_type: 'context', archived: false, target_date: null, status: null, status_override: false, color: '#00f', created_at: '', updated_at: '' },
  { id: 'n2', parent_id: null, name: 'Personal', description: null, node_type: 'context', archived: false, target_date: null, status: null, status_override: false, color: null, created_at: '', updated_at: '' },
]

const ANCHORS: Anchor[] = [
  { id: 'a1', name: 'Morning', time: '06:00', color: '#f59e0b', flexibility: 'strict', strictness: 1, duration_minutes: 60, position: 0, followup_config: null },
  { id: 'a2', name: 'Evening', time: '18:00', color: '#6366f1', flexibility: 'flexible', strictness: 2, duration_minutes: 120, position: 1, followup_config: null },
]

const KANBAN_COLUMNS: KanbanColumn[] = [
  { id: 'k1', name: 'Todo', position: 0, color: null, match_rules: {}, entry_rules: {}, created_by: null },
  { id: 'k2', name: 'Done', position: 1, color: '#888', match_rules: {}, entry_rules: {}, created_by: null },
]

const EMPTY_FILTER = { contextNodeIds: new Set<string>(), anchorIds: new Set<string>(), kanbanColumnIds: new Set<string>() }

function makeWrapper(overrides: Record<string, unknown> = {}) {
  setActivePinia(createPinia())
  return mount(CalendarFilterPanel, {
    props: {
      modelValue: EMPTY_FILTER,
      rootNodes: ROOT_NODES,
      childrenOf: (_id: string) => [],
      anchors: ANCHORS,
      kanbanColumns: KANBAN_COLUMNS,
      ...overrides,
    },
  })
}

describe('CalendarFilterPanel', () => {
  it('renders context node section with root nodes', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Work')
    expect(w.text()).toContain('Personal')
  })

  it('renders anchor section', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Morning')
    expect(w.text()).toContain('Evening')
  })

  it('renders kanban column section', () => {
    const w = makeWrapper()
    expect(w.text()).toContain('Todo')
    expect(w.text()).toContain('Done')
  })

  it('filters anchors by search query', async () => {
    const w = makeWrapper()
    const search = w.find('[data-testid="filter-search"]')
    await search.setValue('Morning')
    expect(w.text()).toContain('Morning')
    expect(w.text()).not.toContain('Evening')
  })

  it('emits update:modelValue with toggled anchor', async () => {
    const w = makeWrapper()
    const btn = w.find('[data-testid="filter-item-anchor-a1"]')
    await btn.trigger('click')
    const emitted = w.emitted('update:modelValue')!
    expect((emitted[0][0] as typeof EMPTY_FILTER).anchorIds.has('a1')).toBe(true)
  })

  it('emits update:modelValue with toggled kanban column', async () => {
    const w = makeWrapper()
    const btn = w.find('[data-testid="filter-item-kanban-k1"]')
    await btn.trigger('click')
    const emitted = w.emitted('update:modelValue')!
    expect((emitted[0][0] as typeof EMPTY_FILTER).kanbanColumnIds.has('k1')).toBe(true)
  })

  it('collapses anchors section on header click', async () => {
    const w = makeWrapper()
    const header = w.find('[data-testid="filter-group-anchors"]')
    await header.trigger('click')
    expect(w.find('[data-testid="filter-item-anchor-a1"]').exists()).toBe(false)
  })

  it('emits close on Escape key', async () => {
    const w = makeWrapper()
    await w.trigger('keydown', { key: 'Escape' })
    expect(w.emitted('close')).toBeTruthy()
  })
})
