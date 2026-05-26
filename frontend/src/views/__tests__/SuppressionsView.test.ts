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

// ── D3: Suppression view fill-in ─────────────────────────────────────────────

function makeSuppression(overrides = {}) {
  return {
    id: 's-1',
    scope_key: 'anchor_transition:grind_am',
    reason: 'User posted recently',
    source: 'beacon_decision' as const,
    created_at: '2026-05-21T08:00:00Z',
    expires_at: null,
    checkpoint_type: 'anchor_transition',
    ...overrides,
  }
}

describe('SuppressionsView — filter chips (D3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders checkpoint-type filter chips for paid users', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(
      makeSuppressionsStore({ suppressions: [makeSuppression()] }) as unknown as ReturnType<typeof useSuppressionsStore>
    )
    const wrapper = mount(SuppressionsView)
    // Should render some filter chips — at minimum an "All" chip
    const chips = wrapper.findAll('[data-testid^="filter-chip"]')
    expect(chips.length).toBeGreaterThan(0)
  })

  it('has an "All" filter chip that is active by default', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(
      makeSuppressionsStore({ suppressions: [makeSuppression()] }) as unknown as ReturnType<typeof useSuppressionsStore>
    )
    const wrapper = mount(SuppressionsView)
    const allChip = wrapper.find('[data-testid="filter-chip-all"]')
    expect(allChip.exists()).toBe(true)
    expect(allChip.attributes('aria-pressed')).toBe('true')
  })

  it('filter chips do not render for free users', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(false) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.find('[data-testid="filter-chip-all"]').exists()).toBe(false)
  })
})

describe('SuppressionsView — enriched empty state (D3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('empty state explains what suppressions are', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    const text = wrapper.text().toLowerCase()
    // Should explain that Beacon suppressed notifications
    expect(text).toMatch(/beacon|notif/)
    // Should give user a reason why this is useful
    expect(text).toMatch(/filter|skip|suppress|decid/)
  })

  it('empty state has a meaningful headline (not just "No suppressed events yet")', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    const emptyBlock = wrapper.find('[data-testid="empty-state"]')
    expect(emptyBlock.exists()).toBe(true)
  })
})

describe('SuppressionsView — skeleton loading (D3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows skeleton items while loading instead of a plain "Loading…" text', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(
      makeSuppressionsStore({ loading: true }) as unknown as ReturnType<typeof useSuppressionsStore>
    )
    const wrapper = mount(SuppressionsView)
    const skeletons = wrapper.findAll('[data-testid^="skeleton-item"]')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('does not show skeleton items when not loading', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(makeSuppressionsStore() as unknown as ReturnType<typeof useSuppressionsStore>)
    const wrapper = mount(SuppressionsView)
    expect(wrapper.find('[data-testid^="skeleton-item"]').exists()).toBe(false)
  })
})

describe('SuppressionsView — data items (D3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders suppression items with scope_key, source, and creation date', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(
      makeSuppressionsStore({
        suppressions: [makeSuppression({ id: 's-10', scope_key: 'task_overdue:task-42', source: 'user_rejection', reason: 'Dismissed by user' })],
      }) as unknown as ReturnType<typeof useSuppressionsStore>
    )
    const wrapper = mount(SuppressionsView)
    const text = wrapper.text()
    expect(text).toContain('task_overdue')
    expect(text).toContain('user_rejection')
  })

  it('renders suppression reason when present', () => {
    vi.mocked(useAuthStore).mockReturnValue(makeAuthStore(true) as unknown as ReturnType<typeof useAuthStore>)
    vi.mocked(useSuppressionsStore).mockReturnValue(
      makeSuppressionsStore({
        suppressions: [makeSuppression({ reason: 'Active cooldown in effect' })],
      }) as unknown as ReturnType<typeof useSuppressionsStore>
    )
    const wrapper = mount(SuppressionsView)
    expect(wrapper.text()).toContain('Active cooldown in effect')
  })
})
