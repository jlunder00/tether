import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: vi.fn() }))
vi.mock('../../stores/suppressions', () => ({ useSuppressionsStore: vi.fn() }))

import { useAuthStore } from '../../stores/auth'
import { useSuppressionsStore } from '../../stores/suppressions'
import SuppressionsView from '../SuppressionsView.vue'

function makeAuthStore(isPaid?: boolean) {
  return {
    user: { user_id: 'u1', username: 'jason', is_admin: false, is_paid: isPaid },
    isAuthenticated: true,
    checked: true,
    checkAuth: vi.fn(),
  }
}

function makeSuppressionsStore(overrides = {}) {
  return {
    suppressions: [],
    loading: false,
    error: null,
    fetch: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('SuppressionsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the suppression history heading', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.text().toLowerCase()).toContain('suppress')
  })

  it('paid user: shows empty state when no suppressions', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.text().toLowerCase()).toContain('no suppressed')
  })

  it('free user (is_paid=false): shows upgrade nudge instead of content', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(false) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.text().toLowerCase()).toMatch(/upgrade|premium|beacon/)
    expect(wrapper.text().toLowerCase()).not.toContain('no suppressed')
  })

  it('free user (is_paid absent/undefined): shows upgrade nudge', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(undefined) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.text().toLowerCase()).toMatch(/upgrade|premium|beacon/)
  })

  it('calls suppressions store fetch on mount (paid user)', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    const store = makeSuppressionsStore()
    vi.mocked(useSuppressionsStore).mockReturnValue(store as unknown as ReturnType<typeof useSuppressionsStore>)
    mount(SuppressionsView)
    expect(store.fetch).toHaveBeenCalled()
  })

  it('does NOT call suppressions store fetch for free user', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(false) as unknown as ReturnType<typeof useAuthStore>)
    const store = makeSuppressionsStore()
    vi.mocked(useSuppressionsStore).mockReturnValue(store as unknown as ReturnType<typeof useSuppressionsStore>)
    mount(SuppressionsView)
    expect(store.fetch).not.toHaveBeenCalled()
  })
})

// Store-level tests (404 handling, 200, network error) are in:
// stores/__tests__/suppressions.test.ts — isolated to avoid vi.mock hoisting interference.
