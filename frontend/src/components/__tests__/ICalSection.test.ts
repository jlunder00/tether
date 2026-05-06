import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/settings' }),
}))

vi.mock('../../stores/ical', () => ({
  useICalStore: vi.fn(),
}))

import { useICalStore } from '../../stores/ical'
import type { ImportResult } from '../../stores/ical'

function makeStore(overrides: Partial<{
  importing: boolean
  lastResult: ImportResult | null
  lastError: string | null
  importFile: () => Promise<ImportResult | null>
  importUrl: () => Promise<ImportResult | null>
  clearResult: () => void
}> = {}) {
  return {
    importing: false,
    lastResult: null,
    lastError: null,
    importFile: vi.fn().mockResolvedValue(null),
    importUrl: vi.fn().mockResolvedValue(null),
    clearResult: vi.fn(),
    ...overrides,
  }
}

async function mountSection(storeOverrides = {}) {
  vi.mocked(useICalStore).mockReturnValue(makeStore(storeOverrides) as any)
  const { default: ICalSection } = await import('../ICalSection.vue')
  return mount(ICalSection, { attachTo: document.body })
}

describe('ICalSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  // ── rendering ──────────────────────────────────────────────────────────────

  it('mounts without error and shows section heading', async () => {
    const wrapper = await mountSection()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.text()).toMatch(/iCal|ICS|Calendar/i)
  })

  it('renders two mode tabs: File and URL', async () => {
    const wrapper = await mountSection()
    expect(wrapper.text()).toContain('File')
    expect(wrapper.text()).toContain('URL')
  })

  it('shows the file drop zone in File mode by default', async () => {
    const wrapper = await mountSection()
    const dropZone = wrapper.find('[data-testid="ical-drop-zone"]')
    expect(dropZone.exists()).toBe(true)
  })

  it('shows the URL input when URL tab is selected', async () => {
    const wrapper = await mountSection()
    const urlTab = wrapper.find('[data-testid="ical-tab-url"]')
    await urlTab.trigger('click')

    const urlInput = wrapper.find('[data-testid="ical-url-input"]')
    expect(urlInput.exists()).toBe(true)
  })

  it('hides the drop zone when URL tab is selected', async () => {
    const wrapper = await mountSection()
    await wrapper.find('[data-testid="ical-tab-url"]').trigger('click')

    const dropZone = wrapper.find('[data-testid="ical-drop-zone"]')
    expect(dropZone.exists()).toBe(false)
  })

  // ── skip_all_day checkbox ─────────────────────────────────────────────────

  it('renders the skip-all-day checkbox', async () => {
    const wrapper = await mountSection()
    const cb = wrapper.find('[data-testid="ical-skip-all-day"]')
    expect(cb.exists()).toBe(true)
  })

  // ── file import ────────────────────────────────────────────────────────────

  it('calls store.importFile when Import button is clicked with a file selected', async () => {
    const importFileMock = vi.fn().mockResolvedValue(null)
    const wrapper = await mountSection({ importFile: importFileMock })

    // Simulate file selection via the hidden input
    const fileInput = wrapper.find('[data-testid="ical-file-input"]')
    expect(fileInput.exists()).toBe(true)

    const file = new File(['BEGIN:VCALENDAR\nEND:VCALENDAR'], 'test.ics', { type: 'text/calendar' })
    Object.defineProperty(fileInput.element, 'files', { value: [file], configurable: true })
    await fileInput.trigger('change')

    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    await importBtn.trigger('click')
    await flushPromises()

    expect(importFileMock).toHaveBeenCalledOnce()
    expect(importFileMock).toHaveBeenCalledWith(file, expect.any(Boolean))
  })

  it('disables the import button when no file is selected', async () => {
    const wrapper = await mountSection()
    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    expect((importBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('disables the import button while importing', async () => {
    const wrapper = await mountSection({ importing: true })
    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    expect((importBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  // ── URL import ─────────────────────────────────────────────────────────────

  it('calls store.importUrl when Import clicked with a URL entered', async () => {
    const importUrlMock = vi.fn().mockResolvedValue(null)
    const wrapper = await mountSection({ importUrl: importUrlMock })

    await wrapper.find('[data-testid="ical-tab-url"]').trigger('click')

    const urlInput = wrapper.find('[data-testid="ical-url-input"]')
    await urlInput.setValue('webcal://example.com/feed.ics')

    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    await importBtn.trigger('click')
    await flushPromises()

    expect(importUrlMock).toHaveBeenCalledOnce()
    expect(importUrlMock).toHaveBeenCalledWith('webcal://example.com/feed.ics', expect.any(Boolean))
  })

  it('disables the import button when URL input is empty', async () => {
    const wrapper = await mountSection()
    await wrapper.find('[data-testid="ical-tab-url"]').trigger('click')

    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    expect((importBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  // ── result display ─────────────────────────────────────────────────────────

  it('shows import counts when lastResult is set', async () => {
    const result: ImportResult = { imported: 3, updated: 1, skipped: 0, errors: [], total_events: 4 }
    const wrapper = await mountSection({ lastResult: result })

    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('imported')
    expect(wrapper.text()).toContain('1')
    expect(wrapper.text()).toContain('updated')
  })

  it('shows a warning message when result.warning is present', async () => {
    const result: ImportResult = {
      imported: 1000, updated: 0, skipped: 0, errors: [], total_events: 1500,
      warning: 'Only first 1000 events were imported',
    }
    const wrapper = await mountSection({ lastResult: result })
    expect(wrapper.text()).toContain('1000')
  })

  it('shows per-event errors when result.errors is non-empty', async () => {
    const result: ImportResult = {
      imported: 2, updated: 0, skipped: 0,
      errors: [{ uid: 'abc', error: 'Parse failed' }],
      total_events: 3,
    }
    const wrapper = await mountSection({ lastResult: result })
    expect(wrapper.text()).toContain('Parse failed')
  })

  // ── error display ──────────────────────────────────────────────────────────

  it('shows lastError when set', async () => {
    const wrapper = await mountSection({ lastError: 'File is too large (max 5 MB).' })
    expect(wrapper.text()).toContain('File is too large')
  })

  it('does not show an error section when lastError is null', async () => {
    const wrapper = await mountSection({ lastError: null })
    const errEl = wrapper.find('[data-testid="ical-error"]')
    expect(errEl.exists()).toBe(false)
  })

  // ── drag and drop ──────────────────────────────────────────────────────────

  it('accepts .ics files dropped on the drop zone', async () => {
    const importFileMock = vi.fn().mockResolvedValue(null)
    const wrapper = await mountSection({ importFile: importFileMock })

    const dropZone = wrapper.find('[data-testid="ical-drop-zone"]')
    const file = new File(['BEGIN:VCALENDAR\nEND:VCALENDAR'], 'events.ics', { type: 'text/calendar' })

    // dragover should not be prevented from default but drop should select file
    await dropZone.trigger('dragover', { dataTransfer: { files: [] } })
    await dropZone.trigger('drop', {
      dataTransfer: { files: [file] },
    })

    // After drop, clicking import should call importFile
    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    expect((importBtn.element as HTMLButtonElement).disabled).toBe(false)
  })

  it('rejects non-.ics files dropped on the drop zone', async () => {
    const wrapper = await mountSection()

    const dropZone = wrapper.find('[data-testid="ical-drop-zone"]')
    const file = new File(['not ics'], 'document.pdf', { type: 'application/pdf' })

    await dropZone.trigger('drop', {
      dataTransfer: { files: [file] },
    })

    // Button should remain disabled (no valid file selected)
    const importBtn = wrapper.find('[data-testid="ical-import-btn"]')
    expect((importBtn.element as HTMLButtonElement).disabled).toBe(true)
    // Error or warning shown
    expect(wrapper.text()).toMatch(/\.ics|ICS|calendar/i)
  })
})
