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
  anthropicConnected: boolean
  anthropicLoading: boolean
  anthropicError: string | null
  anthropicAuthUrl: string | null
  fetchAnthropicStatus: () => Promise<void>
  startAnthropicConnect: () => Promise<string | null>
  completeAnthropicConnect: (code: string) => Promise<void>
  disconnectAnthropic: () => Promise<void>
}> = {}) {
  return {
    anthropicConnected: false,
    anthropicLoading: false,
    anthropicError: null,
    anthropicAuthUrl: null,
    fetchAnthropicStatus: vi.fn().mockResolvedValue(undefined),
    startAnthropicConnect: vi.fn().mockResolvedValue('https://auth.anthropic.com/oauth'),
    completeAnthropicConnect: vi.fn().mockResolvedValue(undefined),
    disconnectAnthropic: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('AnthropicAccountSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore() as any)
  })

  it('mounts without error', async () => {
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows Connect button when anthropicConnected is false', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ anthropicConnected: false }) as any)
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    const btn = wrapper.find('[data-testid="anthropic-connect"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('Connect')
  })

  it('shows Connected badge and Disconnect button when anthropicConnected is true', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ anthropicConnected: true }) as any)
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    expect(wrapper.text()).toContain('Connected')
    const disconnectBtn = wrapper.find('[data-testid="anthropic-disconnect"]')
    expect(disconnectBtn.exists()).toBe(true)
  })

  it('clicking Connect calls store.startAnthropicConnect and shows modal', async () => {
    const startAnthropicConnect = vi.fn().mockResolvedValue('https://auth.anthropic.com/oauth')
    vi.mocked(useIntegrationsStore).mockReturnValue(
      makeStore({ anthropicConnected: false, startAnthropicConnect }) as any
    )
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    await wrapper.find('[data-testid="anthropic-connect"]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(startAnthropicConnect).toHaveBeenCalledOnce()
    // Modal should appear — look for heading text
    expect(wrapper.text()).toContain('Connect your Anthropic account')
  })

  it('Disconnect button shows inline confirmation on click', async () => {
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ anthropicConnected: true }) as any)
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    await wrapper.find('[data-testid="anthropic-disconnect"]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="anthropic-disconnect-confirm"]').exists()).toBe(true)
  })

  it('clicking Confirm calls store.disconnectAnthropic', async () => {
    const disconnectAnthropic = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useIntegrationsStore).mockReturnValue(
      makeStore({ anthropicConnected: true, disconnectAnthropic }) as any
    )
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    // Show the confirmation first
    await wrapper.find('[data-testid="anthropic-disconnect"]').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.find('[data-testid="anthropic-disconnect-confirm"]').trigger('click')
    expect(disconnectAnthropic).toHaveBeenCalledOnce()
  })

  it('modal shows URL with copy button when anthropicAuthUrl is set', async () => {
    const startAnthropicConnect = vi.fn().mockImplementation(async () => {
      return 'https://auth.anthropic.com/oauth'
    })
    vi.mocked(useIntegrationsStore).mockReturnValue(
      makeStore({
        anthropicConnected: false,
        anthropicAuthUrl: 'https://auth.anthropic.com/oauth',
        startAnthropicConnect,
      }) as any
    )
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    await wrapper.find('[data-testid="anthropic-connect"]').trigger('click')
    await wrapper.vm.$nextTick()
    // Should show the auth URL link
    const link = wrapper.find('[data-testid="anthropic-auth-url"]')
    expect(link.exists()).toBe(true)
    // Should show copy button
    const copyBtn = wrapper.find('[data-testid="anthropic-copy-url"]')
    expect(copyBtn.exists()).toBe(true)
  })

  it('Submit calls store.completeAnthropicConnect with input value', async () => {
    const completeAnthropicConnect = vi.fn().mockResolvedValue(undefined)
    const startAnthropicConnect = vi.fn().mockResolvedValue('https://auth.anthropic.com/oauth')
    vi.mocked(useIntegrationsStore).mockReturnValue(
      makeStore({
        anthropicConnected: false,
        anthropicAuthUrl: 'https://auth.anthropic.com/oauth',
        startAnthropicConnect,
        completeAnthropicConnect,
      }) as any
    )
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    // Open the modal
    await wrapper.find('[data-testid="anthropic-connect"]').trigger('click')
    await wrapper.vm.$nextTick()
    // Enter code
    const codeInput = wrapper.find('[data-testid="anthropic-code-input"]')
    await codeInput.setValue('mycode123')
    // Submit
    await wrapper.find('[data-testid="anthropic-submit"]').trigger('click')
    expect(completeAnthropicConnect).toHaveBeenCalledWith('mycode123')
  })

  it('modal error shown when store.anthropicError is set', async () => {
    const startAnthropicConnect = vi.fn().mockResolvedValue('https://auth.anthropic.com/oauth')
    vi.mocked(useIntegrationsStore).mockReturnValue(
      makeStore({
        anthropicConnected: false,
        anthropicAuthUrl: 'https://auth.anthropic.com/oauth',
        anthropicError: 'Invalid code',
        startAnthropicConnect,
      }) as any
    )
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    const wrapper = mount(AnthropicAccountSection)
    // Open the modal
    await wrapper.find('[data-testid="anthropic-connect"]').trigger('click')
    await wrapper.vm.$nextTick()
    // Error should appear in the modal
    expect(wrapper.text()).toContain('Invalid code')
  })

  it('calls fetchAnthropicStatus on mount', async () => {
    const fetchAnthropicStatus = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useIntegrationsStore).mockReturnValue(makeStore({ fetchAnthropicStatus }) as any)
    const { default: AnthropicAccountSection } = await import('../AnthropicAccountSection.vue')
    mount(AnthropicAccountSection)
    expect(fetchAnthropicStatus).toHaveBeenCalledOnce()
  })
})
