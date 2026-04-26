import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/settings' }),
}))

// Mock the integrations store module
vi.mock('../../stores/integrations', () => ({
  useIntegrationsStore: vi.fn(),
}))

import { useIntegrationsStore } from '../../stores/integrations'

function makeStore(overrides: Partial<{
  gcalConnected: boolean
  loading: boolean
  error: string | null
  fetchGCalStatus: () => Promise<void>
  connectGCal: () => void
  disconnectGCal: () => Promise<void>
}> = {}) {
  return {
    gcalConnected: false,
    loading: false,
    error: null,
    fetchGCalStatus: vi.fn().mockResolvedValue(undefined),
    connectGCal: vi.fn(),
    disconnectGCal: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('GoogleCalendarSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore() as any)
  })

  it('mounts without error', async () => {
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows "Not connected" status when gcalConnected is false', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: false }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    expect(wrapper.text()).toContain('Not connected')
  })

  it('shows "Connected" status when gcalConnected is true', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: true }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    expect(wrapper.text()).toContain('Connected')
  })

  it('shows a Connect button when not connected', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: false }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    const btn = wrapper.find('[data-testid="gcal-connect"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('Connect')
  })

  it('shows a Disconnect button when connected', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: true }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    const btn = wrapper.find('[data-testid="gcal-disconnect"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('Disconnect')
  })

  it('calls connectGCal when Connect button is clicked', async () => {
    const connectGCal = vi.fn()
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: false, connectGCal }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    await wrapper.find('[data-testid="gcal-connect"]').trigger('click')
    expect(connectGCal).toHaveBeenCalledOnce()
  })

  it('calls disconnectGCal when Disconnect button is clicked', async () => {
    const disconnectGCal = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ gcalConnected: true, disconnectGCal }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    await wrapper.find('[data-testid="gcal-disconnect"]').trigger('click')
    expect(disconnectGCal).toHaveBeenCalledOnce()
  })

  it('calls fetchGCalStatus on mount', async () => {
    const fetchGCalStatus = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ fetchGCalStatus }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    mount(GoogleCalendarSection)
    expect(fetchGCalStatus).toHaveBeenCalledOnce()
  })

  it('shows loading state during operations', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ loading: true }) as any)
    const { default: GoogleCalendarSection } = await import('../GoogleCalendarSection.vue')
    const wrapper = mount(GoogleCalendarSection)
    // Buttons should be disabled during loading
    const buttons = wrapper.findAll('button')
    const disabledBtn = buttons.find(b => (b.element as HTMLButtonElement).disabled)
    expect(disabledBtn).toBeDefined()
  })
})
