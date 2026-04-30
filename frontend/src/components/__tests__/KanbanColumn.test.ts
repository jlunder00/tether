import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { KanbanColumn as KanbanColumnType } from '../../stores/kanban'
import KanbanColumn from '../KanbanColumn.vue'

// Mock api module (KanbanColumn imports it for onTaskUpdate)
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

describe('KanbanColumn drop target', () => {
  let wrapper: ReturnType<typeof mount>
  let body: ReturnType<typeof wrapper.find>

  beforeEach(() => {
    setActivePinia(createPinia())
    wrapper = mount(KanbanColumn, { props: { column: testColumn, tasks: [] } })
    body = wrapper.find('.flex-1.overflow-y-auto')
  })

  it('emits task-drop with taskId and columnId on valid drop', async () => {
    await body.trigger('drop', {
      dataTransfer: {
        getData: () => JSON.stringify({ taskId: 'task-1' }),
      },
    })
    expect(wrapper.emitted('task-drop')).toBeTruthy()
    expect(wrapper.emitted('task-drop')![0]).toEqual(['task-1', 'col_done'])
  })

  it('does not emit on drop with malformed JSON', async () => {
    await body.trigger('drop', {
      dataTransfer: { getData: () => 'not-json' },
    })
    expect(wrapper.emitted('task-drop')).toBeFalsy()
  })

  it('does not emit when taskId is not a string', async () => {
    await body.trigger('drop', {
      dataTransfer: { getData: () => JSON.stringify({ taskId: 123 }) },
    })
    expect(wrapper.emitted('task-drop')).toBeFalsy()
  })

  it('does not emit when taskId is missing from payload', async () => {
    await body.trigger('drop', {
      dataTransfer: { getData: () => JSON.stringify({}) },
    })
    expect(wrapper.emitted('task-drop')).toBeFalsy()
  })

  it('applies highlight class on dragenter', async () => {
    await body.trigger('dragenter')
    expect(body.classes()).toContain('ring-2')
  })

  it('removes highlight after final dragleave (counter pattern)', async () => {
    await body.trigger('dragenter')
    await body.trigger('dragenter')
    await body.trigger('dragleave')
    expect(body.classes()).toContain('ring-2')
    await body.trigger('dragleave')
    expect(body.classes()).not.toContain('ring-2')
  })
})

describe('KanbanColumn motif', () => {
  function mountWith(rules: Partial<Pick<KanbanColumnType, 'match_rules' | 'entry_rules'>>) {
    setActivePinia(createPinia())
    return mount(KanbanColumn, {
      props: {
        column: { ...testColumn, match_rules: {}, entry_rules: {}, ...rules },
        tasks: [],
      },
    })
  }

  const cases: Array<[string, string]> = [
    ['pending', 'quiet'],
    ['in_progress', 'focus'],
    ['done', 'calm'],
    ['skipped', 'dusk'],
    ['blocked', 'energy'],
  ]

  for (const [status, expected] of cases) {
    it(`maps match_rules.status="${status}" to motif="${expected}"`, () => {
      const w = mountWith({ match_rules: { status } })
      expect(w.find('[data-motif]').attributes('data-motif')).toBe(expected)
    })
  }

  it('falls back to entry_rules.set_status when match_rules has none', () => {
    const w = mountWith({ match_rules: {}, entry_rules: { set_status: 'done' } })
    expect(w.find('[data-motif]').attributes('data-motif')).toBe('calm')
  })

  it('falls back to "anchor" when no status rule is present', () => {
    const w = mountWith({ match_rules: { plan_date: 'not_null' }, entry_rules: {} })
    expect(w.find('[data-motif]').attributes('data-motif')).toBe('anchor')
  })
})
