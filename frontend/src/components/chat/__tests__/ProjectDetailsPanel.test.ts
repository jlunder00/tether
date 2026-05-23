import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { reactive } from 'vue'

vi.mock('../../../stores/context', () => ({
  useContextStore: vi.fn(),
}))

import { useContextStore } from '../../../stores/context'
const mockUseContextStore = vi.mocked(useContextStore)

function makeSection(overrides = {}) {
  return {
    section_type: 'details',
    name: 'main',
    body: 'Default context body',
    position: 0,
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function makeCtxStore(opts: { section?: ReturnType<typeof makeSection> | null; files?: any[] } = {}) {
  return reactive({
    nodes: {},
    fetchSection: vi.fn().mockResolvedValue(opts.section ?? null),
    saveSection: vi.fn().mockResolvedValue(makeSection()),
    fetchSectionFiles: vi.fn().mockResolvedValue(opts.files ?? []),
  })
}

describe('ProjectDetailsPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts without error', async () => {
    mockUseContextStore.mockReturnValue(makeCtxStore() as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: null } })
    expect(wrapper.exists()).toBe(true)
  })

  it('loads section when nodeId prop is set', async () => {
    const ctxStore = makeCtxStore({ section: makeSection({ body: 'Loaded content' }) })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    expect(ctxStore.fetchSection).toHaveBeenCalledWith('node-1', 'details')
  })

  it('populates textarea with loaded section body', async () => {
    const ctxStore = makeCtxStore({ section: makeSection({ body: 'My project context' }) })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    const textarea = wrapper.find('textarea')
    expect(textarea.element.value).toContain('My project context')
  })

  it('reloads section when nodeId prop changes', async () => {
    const ctxStore = makeCtxStore({ section: makeSection() })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()
    ctxStore.fetchSection.mockClear()

    await wrapper.setProps({ nodeId: 'node-2' })
    await flushPromises()

    expect(ctxStore.fetchSection).toHaveBeenCalledWith('node-2', 'details')
  })

  it('autosave fires after 800ms debounce on input', async () => {
    vi.useFakeTimers()
    const ctxStore = makeCtxStore({ section: makeSection({ body: '' }) })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Updated content')
    await textarea.trigger('input')

    // Not saved yet
    expect(ctxStore.saveSection).not.toHaveBeenCalled()

    // Advance 800ms
    vi.advanceTimersByTime(800)
    await flushPromises()

    expect(ctxStore.saveSection).toHaveBeenCalledWith('node-1', 'details', 'Updated content')

    vi.useRealTimers()
  })

  it('blur saves immediately and shows Saved indicator', async () => {
    const ctxStore = makeCtxStore({ section: makeSection({ body: '' }) })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    const textarea = wrapper.find('textarea')
    await textarea.setValue('Blurred content')
    await textarea.trigger('blur')
    await flushPromises()

    expect(ctxStore.saveSection).toHaveBeenCalledWith('node-1', 'details', 'Blurred content')
    // Saved indicator shows
    expect(wrapper.text()).toContain('Saved')
  })

  it('tab switch between Details and Files works', async () => {
    const ctxStore = makeCtxStore({
      section: makeSection(),
      files: [{ name: 'readme.md', size: 1024, position: 0, updated_at: '2026-01-01T00:00:00Z' }],
    })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    // Initially on Details tab
    expect(wrapper.find('textarea').exists()).toBe(true)

    // Click Files tab
    const filesTab = wrapper.findAll('button').find(b => b.text() === 'Files')
    expect(filesTab).toBeDefined()
    await filesTab!.trigger('click')

    // Should now show files tab content (dropzone)
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).toContain('Drop files here')
  })

  it('emits collapse when collapse button is clicked', async () => {
    mockUseContextStore.mockReturnValue(makeCtxStore() as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: null } })

    const collapseBtn = wrapper.find('[data-testid="collapse-btn"]')
    expect(collapseBtn.exists()).toBe(true)
    await collapseBtn.trigger('click')

    expect(wrapper.emitted('collapse')).toBeTruthy()
  })

  it('back-to-back saves: older fade timer does not clear newer Saved indicator', async () => {
    // Regression guard: the savedAt fade-out timer captures the save's timestamp
    // in a closure and only clears savedAt if it's still equal. Otherwise a fast
    // second save would be silenced by the first save's fade timer.
    vi.useFakeTimers()
    const ctxStore = makeCtxStore({ section: makeSection({ body: 'initial' }) })
    mockUseContextStore.mockReturnValue(ctxStore as any)

    const { default: ProjectDetailsPanel } = await import('../ProjectDetailsPanel.vue')
    const wrapper = mount(ProjectDetailsPanel, { props: { nodeId: 'node-1' } })
    await flushPromises()

    // First save via blur — sets savedAt=T1 and schedules clear-T1 for +2000ms
    const textarea = wrapper.find('[data-testid="context-textarea"]')
    await textarea.setValue('first edit')
    await textarea.trigger('blur')
    await flushPromises()
    expect(wrapper.text()).toContain('Saved')

    // Advance 1900ms — first fade timer hasn't fired yet
    vi.advanceTimersByTime(1900)
    expect(wrapper.text()).toContain('Saved')

    // Second save while first fade is still pending — must reset savedAt to T2
    await textarea.setValue('second edit')
    await textarea.trigger('blur')
    await flushPromises()
    expect(wrapper.text()).toContain('Saved')

    // Now advance past the first fade timer's 2000ms total (200ms remaining).
    // The first timer fires here — it MUST NOT clear savedAt because savedAt=T2 now.
    vi.advanceTimersByTime(200)
    await flushPromises()
    expect(wrapper.text()).toContain('Saved')

    // Advance to past T2 + 2000ms — second fade timer fires, clears savedAt
    vi.advanceTimersByTime(2000)
    await flushPromises()
    expect(wrapper.text()).not.toContain('Saved')

    vi.useRealTimers()
  })
})
