/**
 * MiniCalendarDay — individual day cell with useDropZone drop target
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

vi.mock('../../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

const mockIsOver = ref(false)
let capturedOnDrop: ((payload: unknown, ctx: unknown) => void) | null = null

vi.mock('../../../composables/useDropZone', () => ({
  useDropZone: vi.fn((opts: any) => {
    capturedOnDrop = opts.onDrop
    return {
      isOver: mockIsOver,
      dropHandlers: {
        onDragEnter: vi.fn(),
        onDragOver: vi.fn(),
        onDragLeave: vi.fn(),
        onDrop: vi.fn(),
      },
    }
  }),
}))

describe('MiniCalendarDay — drop zone', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockIsOver.value = false
    capturedOnDrop = null
  })

  async function mountDay(props: Record<string, unknown> = {}) {
    const { default: MiniCalendarDay } = await import('../MiniCalendarDay.vue')
    return mount(MiniCalendarDay, {
      props: {
        date: '2026-05-15',
        taskCount: 0,
        isToday: false,
        ...props,
      },
    })
  }

  it('renders a day cell with the correct date', async () => {
    const w = await mountDay()
    expect(w.find('[data-date="2026-05-15"]').exists()).toBe(true)
  })

  it('applies highlight class when isOver is true', async () => {
    const w = await mountDay()
    const cell = w.find('[data-date="2026-05-15"]')

    mockIsOver.value = true
    await w.vm.$nextTick()

    expect(cell.classes()).toContain('ring-1')
  })

  it('emits task-dropped with taskId and date when a task payload is dropped', async () => {
    const w = await mountDay({ date: '2026-06-01' })

    capturedOnDrop!({ type: 'task', taskId: 'task-abc', fromAnchorId: 'morning' }, undefined)
    await w.vm.$nextTick()

    expect(w.emitted('task-dropped')).toBeTruthy()
    const event = w.emitted('task-dropped')![0][0] as any
    expect(event.taskId).toBe('task-abc')
    expect(event.date).toBe('2026-06-01')
    expect(event.fromAnchorId).toBe('morning')
  })

  it('does not emit task-dropped when payload has no taskId', async () => {
    const w = await mountDay()

    capturedOnDrop!({ type: 'task' }, undefined)

    expect(w.emitted('task-dropped')).toBeFalsy()
  })

  it('highlights today cell with today styling', async () => {
    const w = await mountDay({ isToday: true })
    // text-[--accent] is on the day-number span, not the root cell div
    const daySpan = w.find('[data-date="2026-05-15"] span')
    expect(daySpan.classes()).toContain('text-[--accent]')
  })

  it('shows task count when taskCount > 0', async () => {
    const w = await mountDay({ taskCount: 3 })
    expect(w.text()).toContain('3')
  })
})
