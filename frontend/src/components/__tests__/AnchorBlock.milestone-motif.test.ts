/**
 * AnchorBlock — milestone GroupContainer motif picker (Bug 3)
 *
 * When a milestone has >1 tasks in an anchor, it renders inside a
 * GroupContainer. That container should expose a MotifPicker in the
 * #header-right slot so users can set the milestone's motif colour —
 * exactly like the context GroupContainer already does.
 *
 * Previously the milestone GroupContainer had no #header-right slot,
 * so there was no way to set its motif from the anchor view.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => ({}) })),
}))

vi.mock('../../composables/useDropZone', () => ({
  useDropZone: vi.fn(() => ({
    isOver: { value: false },
    dropHandlers: {
      onDragEnter: vi.fn(),
      onDragOver: vi.fn(),
      onDragLeave: vi.fn(),
      onDrop: vi.fn(),
    },
  })),
}))

vi.mock('../../composables/useSlideOver', () => ({
  useSlideOver: () => ({
    push: vi.fn(),
    pop: vi.fn(),
    stack: { value: [] },
    close: vi.fn(),
    restoreFromUrl: vi.fn(),
  }),
}))

/** Minimal Milestone fixture with two tasks so the GroupContainer renders */
const MILESTONE_ID = 'ms-1'

// Full Milestone object — task_ids is required by the computed taskMilestones
const MILESTONE = {
  id: MILESTONE_ID,
  name: 'Sprint Goal',
  color: '#3b82f6',
  motif: null,
  status: 'active' as const,
  description: null,
  target_date: null,
  status_override: false,
  context_subject: 'Work',
  created_at: '2026-01-01',
  updated_at: '2026-01-01',
  task_count: 2,
  done_count: 0,
  task_ids: ['t-1', 't-2'],
  tasks: [],
}

const TASKS = [
  { id: 't-1', text: 'Task A', status: 'pending', position: 0, context_subject: null, context_node_id: null, blocks: [], blocked_by: [], followup_config: null, description: null },
  { id: 't-2', text: 'Task B', status: 'pending', position: 1, context_subject: null, context_node_id: null, blocks: [], blocked_by: [], followup_config: null, description: null },
]

async function mountBlock() {
  const { default: AnchorBlock } = await import('../AnchorBlock.vue')
  const { usePlanStore } = await import('../../stores/plan')
  const { useMilestoneStore } = await import('../../stores/milestones')

  const planStore = usePlanStore()
  planStore.plan = {
    date: '2026-05-05',
    anchors: {
      'a1': { tasks: TASKS as any[], notes: '' },
    },
    acknowledgements: {},
    check_in_log: [],
  } as any

  // Populate all — taskMilestones computed derives from this
  const msStore = useMilestoneStore()
  msStore.all = [MILESTONE] as any[]

  return { wrapper: mount(AnchorBlock, {
    props: {
      anchorId: 'a1',
      anchorName: 'Morning',
      time: '08:00',
      color: '#fff',
    },
  }), msStore }
}

describe('AnchorBlock — milestone GroupContainer motif picker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders a milestone-motif-picker when milestone group has >1 tasks', async () => {
    const { wrapper } = await mountBlock()
    await flushPromises()
    const picker = wrapper.find('[data-testid="milestone-motif-picker"]')
    expect(picker.exists()).toBe(true)
  })

  it('calls milestoneStore.patchMilestone with motif when MotifPicker emits update', async () => {
    const { wrapper, msStore } = await mountBlock()
    await flushPromises()

    const patchSpy = vi.spyOn(msStore, 'patchMilestone').mockResolvedValue(undefined as any)

    // Find and click a swatch inside the milestone-motif-picker
    const pickerContainer = wrapper.find('[data-testid="milestone-motif-picker"]')
    expect(pickerContainer.exists()).toBe(true)

    // Trigger update:modelValue on the MotifPicker component inside that container
    const motifPicker = pickerContainer.findComponent({ name: 'MotifPicker' })
    expect(motifPicker.exists()).toBe(true)
    await motifPicker.vm.$emit('update:modelValue', 'focus')
    await flushPromises()

    expect(patchSpy).toHaveBeenCalledWith(MILESTONE_ID, { motif: 'focus' })
  })
})
