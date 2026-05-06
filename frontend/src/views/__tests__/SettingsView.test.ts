import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/settings' }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn((url: string) => {
    if (url === '/api/llm-config') {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          models: {},
          llm: {
            preferred_backend: 'anthropic',
            thinking_enabled: false,
            thinking_budget: 8000,
            beacon_score_threshold: 10,
            beacon_cooldown_minutes: 30,
          },
          model_roles: [],
          defaults: { models: {}, llm: {} },
        }),
      })
    }
    return Promise.resolve({ ok: true, json: async () => ({}) })
  }),
}))

vi.mock('../../components/GoogleCalendarSection.vue', () => ({
  default: { template: '<div />' },
}))
vi.mock('../../components/AnthropicAccountSection.vue', () => ({
  default: { template: '<div />' },
}))
vi.mock('../../components/ConnectionsSection.vue', () => ({
  default: { template: '<div />' },
}))
vi.mock('../../components/ICalSection.vue', () => ({
  default: { template: '<div data-testid="ical-section-stub" />' },
}))

describe('SettingsView - Appearance theme picker', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    delete document.documentElement.dataset.theme
    delete document.documentElement.dataset.typeVoice
    delete document.documentElement.dataset.themeSwap
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('renders a button for every THEMES entry with name and swatch', async () => {
    const { THEMES } = await import('../../composables/useTheme')
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    for (const theme of THEMES) {
      const btn = wrapper.find(`button[title="${theme.name}"]`)
      expect(btn.exists()).toBe(true)
      expect(btn.text()).toContain(theme.name)
      const swatch = btn.find('span[style*="linear-gradient"]')
      expect(swatch.exists()).toBe(true)
    }
  })

  it('shows a tier badge on non-free themes', async () => {
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    // Free themes have no badge
    const tetherBtn = wrapper.find('button[title="The Tether"]')
    expect(tetherBtn.text()).not.toContain('paid')
    expect(tetherBtn.text()).not.toContain('oss')

    // Paid theme shows a badge
    const terminalBtn = wrapper.find('button[title="Terminal"]')
    expect(terminalBtn.text().toLowerCase()).toMatch(/paid|oss/)
  })

  it('clicking a free theme applies it and persists to localStorage', async () => {
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.find('button[title="Horizon"]').trigger('click')

    expect(document.documentElement.dataset.theme).toBe('horizon')
    expect(localStorage.getItem('tether-theme')).toBe('horizon')
  })

  it('clicking a paid theme previews on DOM but does NOT persist, and shows upgrade nudge', async () => {
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.find('button[title="Terminal"]').trigger('click')

    // DOM was previewed
    expect(document.documentElement.dataset.theme).toBe('terminal')
    // But not persisted (user is not paid)
    expect(localStorage.getItem('tether-theme')).toBeNull()
    // Upgrade nudge shown
    expect(wrapper.text()).toContain('Terminal')
    expect(wrapper.text().toLowerCase()).toContain('upgrade')
  })

  it('hovering a theme button previews it via document.documentElement.dataset.theme', async () => {
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()

    await wrapper.find('button[title="Solstice"]').trigger('mouseenter')
    expect(document.documentElement.dataset.theme).toBe('solstice')
  })
})

describe('SettingsView - ICalSection integration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('renders ICalSection in the settings page', async () => {
    const { default: SettingsView } = await import('../SettingsView.vue')
    const wrapper = mount(SettingsView, {
      global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
    })
    await flushPromises()
    expect(wrapper.find('[data-testid="ical-section-stub"]').exists()).toBe(true)
  })
})
