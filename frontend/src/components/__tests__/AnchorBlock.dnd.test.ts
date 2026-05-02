/**
 * Track 3: AnchorBlock DnD enhancements
 *
 * Tests for:
 *  1. Container-level useDropZone on anchor card content div (fixes empty-anchor drop)
 *  2. Drag wrapper payload includes superset format (type:'task', title, fromAnchorId, fromDate)
 *  3. Source task hidden (v-show=false) while dragging
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

const mockContainerIsOver = ref(false)
let capturedContainerOnDrop: ((payload: unknown, ctx: unknown) => void) | null = null

vi.mock('../../composables/useDropZone', () => ({
  useDropZone: vi.fn((opts: any) => {
    capturedContainerOnDrop = opts.onDrop
    return {
      isOver: mockContainerIsOver,
      dropHandlers: {
        onDragEnter: vi.fn(),
        onDragOver: vi.fn(),
        onDragLeave: vi.fn(),
        onDrop: vi.fn(),
      },
    }
  }),
}))

describe('AnchorBlock — container drop zone (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockContainerIsOver.value = false
    capturedContainerOnDrop = null
  })

  async function mountBlock(props: Record<string, unknown> = {}) {
    const { default: AnchorBlock } = await import('../AnchorBlock.vue')
    return mount(AnchorBlock, {
      props: {
        anchorId: 'a1',
        anchorName: 'Morning',
        time: '08:00',
        color: '#fff',
        ...props,
      },
    })
  }

  it('renders a drop zone container element with useDropZone handlers', async () => {
    await mountBlock()
    // useDropZone should have been called (capturedOnDrop set)
    expect(capturedContainerOnDrop).not.toBeNull()
  })

  it('drop on empty anchor calls store.moveTask when task is from different anchor', async () => {
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    const moveSpy = vi.spyOn(store, 'moveTask').mockResolvedValue(undefined)

    await mountBlock()

    // Simulate a drop from a different anchor
    capturedContainerOnDrop!({
      type: 'task',
      taskId: 'task-99',
      title: 'Some task',
      fromAnchorId: 'other-anchor',
      fromDate: '2026-05-01',
    }, undefined)

    expect(moveSpy).toHaveBeenCalledOnce()
  })

  it('drop on empty anchor calls store.reorderTask when task is from same anchor and date', async () => {
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    store.plan = {
      date: '2026-05-01',
      anchors: { a1: { tasks: [], notes: '' } },
    } as any
    const reorderSpy = vi.spyOn(store, 'reorderTask').mockResolvedValue(undefined)

    await mountBlock()

    // Simulate a drop from SAME anchor and date
    capturedContainerOnDrop!({
      type: 'task',
      taskId: 'task-99',
      title: 'Some task',
      fromAnchorId: 'a1',
      fromDate: store.activeDate,
    }, undefined)

    expect(reorderSpy).toHaveBeenCalledOnce()
  })
})

describe('AnchorBlock — drag wrapper superset payload (Track 3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockContainerIsOver.value = false
  })

  async function mountBlockWithTask() {
    const { default: AnchorBlock } = await import('../AnchorBlock.vue')
    const { usePlanStore } = await import('../../stores/plan')
    const store = usePlanStore()
    store.plan = {
      date: '2026-05-01',
      anchors: {
        a1: {
          tasks: [{ id: 'task-1', text: 'Hello', status: 'pending', position: 0 } as any],
          notes: '',
        },
      },
    } as any

    return mount(AnchorBlock, {
      props: { anchorId: 'a1', anchorName: 'Morning', time: '08:00', color: '#fff' },
      attachTo: document.body,
    })
  }

  it('dragstart payload includes type:"task" field', async () => {
    const w = await mountBlockWithTask()
    const wrapper = w.find('[data-task-id="task-1"]')
    const setData = vi.fn()

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData },
    })

    const payload = JSON.parse(setData.mock.calls[0][1])
    expect(payload.type).toBe('task')
  })

  it('dragstart payload includes title (task text)', async () => {
    const w = await mountBlockWithTask()
    const wrapper = w.find('[data-task-id="task-1"]')
    const setData = vi.fn()

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData },
    })

    const payload = JSON.parse(setData.mock.calls[0][1])
    expect(payload.title).toBe('Hello')
  })

  it('dragstart payload includes fromAnchorId and fromDate', async () => {
    const w = await mountBlockWithTask()
    const wrapper = w.find('[data-task-id="task-1"]')
    const setData = vi.fn()

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData },
    })

    const payload = JSON.parse(setData.mock.calls[0][1])
    expect(payload.fromAnchorId).toBe('a1')
    expect(payload.fromDate).toBeTruthy()
  })

  it('task wrapper is hidden while dragging and visible after dragend', async () => {
    const w = await mountBlockWithTask()
    const wrapper = w.find('[data-task-id="task-1"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })
    // Advance rAF so source-hiding applies
    await new Promise(r => requestAnimationFrame(r))
    await w.vm.$nextTick()
    expect(wrapper.isVisible()).toBe(false)

    await wrapper.trigger('dragend')
    expect(wrapper.isVisible()).toBe(true)
  })

  it('task wrapper is still visible immediately after dragstart (ghost capture window — rAF not yet fired)', async () => {
    // Browsers capture the drag ghost image after dragstart handlers complete but
    // before rAF. Source hiding must be deferred to rAF so the ghost snapshot is
    // taken from a still-visible element.
    const rafCallbacks: FrameRequestCallback[] = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      rafCallbacks.push(cb)
      return 0
    })

    const w = await mountBlockWithTask()
    const wrapper = w.find('[data-task-id="task-1"]')

    await wrapper.trigger('dragstart', {
      dataTransfer: { effectAllowed: '', setData: vi.fn() },
    })

    // Ghost capture window: wrapper must still be visible before rAF fires
    expect(wrapper.isVisible()).toBe(true)

    // Fire rAF → hiding applies
    rafCallbacks.forEach(cb => cb(0))
    await w.vm.$nextTick()
    expect(wrapper.isVisible()).toBe(false)

    vi.restoreAllMocks()
  })
})
