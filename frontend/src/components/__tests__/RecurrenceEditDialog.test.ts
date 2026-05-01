import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import RecurrenceEditDialog from '../RecurrenceEditDialog.vue'

let currentWrapper: ReturnType<typeof mount> | null = null

afterEach(() => {
  currentWrapper?.unmount()
  currentWrapper = null
})

function make(overrides: Record<string, unknown> = {}) {
  currentWrapper = mount(RecurrenceEditDialog, {
    props: {
      visible: true,
      mode: 'event' as const,
      action: 'edit' as const,
      ...overrides,
    },
    attachTo: document.body,
  })
  return currentWrapper
}

function getDialog() {
  return document.querySelector('[data-testid="recurrence-edit-dialog"]') as HTMLElement | null
}

describe('RecurrenceEditDialog', () => {
  it('renders with (event, edit) heading', () => {
    make()
    expect(getDialog()?.textContent).toContain('Edit recurring event')
  })

  it('renders with (event, move) heading', () => {
    make({ action: 'move' })
    expect(getDialog()?.textContent).toContain('Move recurring event')
  })

  it('renders with (event, delete) heading', () => {
    make({ action: 'delete' })
    expect(getDialog()?.textContent).toContain('Delete recurring event')
  })

  it('renders with (task, edit) heading', () => {
    make({ mode: 'task', action: 'edit' })
    expect(getDialog()?.textContent).toContain('Edit recurring task')
  })

  it('renders with (task, delete) heading', () => {
    make({ mode: 'task', action: 'delete' })
    expect(getDialog()?.textContent).toContain('Delete recurring task')
  })

  it('confirm button is red for delete action', () => {
    make({ action: 'delete' })
    const btn = document.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    expect(btn.className).toContain('bg-[--status-block-bg]')
  })

  it('confirm button is indigo for edit action', () => {
    make({ action: 'edit' })
    const btn = document.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    expect(btn.className).toContain('bg-[--accent]')
  })

  it('confirm button label is "Delete" for delete action', () => {
    make({ action: 'delete' })
    const btn = document.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    expect(btn.textContent?.trim()).toBe('Delete')
  })

  it('emits confirm with selected scope', async () => {
    const w = make()
    const radioAll = document.querySelector('[data-testid="scope-all"]') as HTMLInputElement
    radioAll.checked = true
    radioAll.dispatchEvent(new Event('change'))
    const btn = document.querySelector('[data-testid="recurrence-edit-confirm"]') as HTMLElement
    btn.click()
    expect(w.emitted('confirm')?.[0]).toEqual(['all'])
  })

  it('emits cancel on cancel button click', () => {
    const w = make()
    const btn = document.querySelector('[data-testid="recurrence-edit-cancel"]') as HTMLElement
    btn.click()
    expect(w.emitted('cancel')).toBeTruthy()
  })

  it('does not render when visible is false', () => {
    make({ visible: false })
    expect(getDialog()).toBeNull()
  })
})
