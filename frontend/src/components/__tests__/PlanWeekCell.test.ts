/**
 * PlanWeekCell — drop handler
 *
 * Verifies that:
 *   1. Dropping a task card onto the cell calls moveTaskToAnchor with correct args
 *   2. Drop with no dataTransfer payload is a no-op
 *   3. Drop with malformed JSON is a no-op (does not throw)
 *   4. Visual drop-over state is set on dragover and cleared on dragleave
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

// Minimal TaskCard stub so PlanWeekCell can render without all TaskCard deps
vi.mock('../TaskCard.vue', () => ({
  default: { template: '<div data-testid="task-card-stub" />' },
}))

describe('PlanWeekCell', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountCell(props: Record<string, unknown> = {}) {
    const { default: PlanWeekCell } = await import('../plan/PlanWeekCell.vue')
    return mount(PlanWeekCell, {
      props: {
        date: '2026-05-05',
        anchorId: 'anchor-deep-work',
        anchorName: 'Deep Work',
        tasks: [],
        ...props,
      },
    })
  }

  it('calls moveTaskToAnchor with correct taskId, newDate and anchorId on drop', async () => {
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    const spy = vi.spyOn(store, 'moveTaskToAnchor').mockResolvedValue(undefined)

    const wrapper = await mountCell()
    const dropZone = wrapper.find('[data-testid="week-cell-drop"]')

    const payload = JSON.stringify({ taskId: 'task-abc', fromAnchorId: 'morning', fromDate: '2026-05-03' })
    const dt = { getData: vi.fn(() => payload), dropEffect: 'move' }
    await dropZone.trigger('drop', { dataTransfer: dt })

    expect(spy).toHaveBeenCalledOnce()
    expect(spy).toHaveBeenCalledWith({ taskId: 'task-abc', newDate: '2026-05-05', anchorId: 'anchor-deep-work' })
  })

  it('is a no-op when drop has no dataTransfer payload', async () => {
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    const spy = vi.spyOn(store, 'moveTaskToAnchor').mockResolvedValue(undefined)

    const wrapper = await mountCell()
    const dropZone = wrapper.find('[data-testid="week-cell-drop"]')

    const dt = { getData: vi.fn(() => ''), dropEffect: 'move' }
    await dropZone.trigger('drop', { dataTransfer: dt })

    expect(spy).not.toHaveBeenCalled()
  })

  it('is a no-op and does not throw when drop payload is malformed JSON', async () => {
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    const spy = vi.spyOn(store, 'moveTaskToAnchor').mockResolvedValue(undefined)

    const wrapper = await mountCell()
    const dropZone = wrapper.find('[data-testid="week-cell-drop"]')

    const dt = { getData: vi.fn(() => 'not valid json'), dropEffect: 'move' }
    await expect(dropZone.trigger('drop', { dataTransfer: dt })).resolves.not.toThrow()
    expect(spy).not.toHaveBeenCalled()
  })

  it('sets ring class on dragenter and clears it on dragleave', async () => {
    const wrapper = await mountCell()
    const dropZone = wrapper.find('[data-testid="week-cell-drop"]')

    await dropZone.trigger('dragenter')
    expect(dropZone.classes()).toContain('ring-1')

    await dropZone.trigger('dragleave')
    expect(dropZone.classes()).not.toContain('ring-1')
  })

  it('renders task stubs when tasks prop is populated', async () => {
    const tasks = [
      { id: 't1', text: 'Task one', status: 'pending', position: 0 },
      { id: 't2', text: 'Task two', status: 'done', position: 1 },
    ]
    const wrapper = await mountCell({ tasks })
    const cards = wrapper.findAll('[data-testid="task-card-stub"]')
    expect(cards).toHaveLength(2)
  })
})
