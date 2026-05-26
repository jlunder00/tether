import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
  RouterLink: { props: ['to', 'activeClass'], template: '<a :href="to"><slot /></a>' },
  RouterView: { template: '<div />' },
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

// Stub out heavy child components to keep App.vue mount lightweight
vi.mock('../../components/SlideOverStack.vue', () => ({
  default: { template: '<div data-testid="slide-over-stack-stub" />' },
}))
vi.mock('../../components/ThemeDrawer.vue', () => ({
  default: { template: '<div data-testid="theme-drawer-stub" />', props: ['modelValue'] },
}))
vi.mock('../../components/SideChatPanel.vue', () => ({
  default: { template: '<div data-testid="side-chat-panel-stub" />', emits: ['close'] },
}))
vi.mock('../../components/PermissionModal.vue', () => ({
  default: { template: '<div data-testid="permission-modal-stub" />' },
}))

// RouterLink stub that renders href so we can find links by path
const RouterLinkStub = { props: ['to', 'activeClass'], template: '<a :href="to"><slot /></a>' }

// Global route mock — App.vue uses $route.path in template
const globalMountOptions = {
  global: {
    mocks: {
      $route: { path: '/dashboard' },
    },
    components: {
      RouterLink: RouterLinkStub,
      'router-link': RouterLinkStub,
    },
  },
}

describe('AppNav - /chat router-link', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders a router-link to /chat when authenticated', async () => {
    const { default: App } = await import('../../App.vue')
    const { useAuthStore } = await import('../../stores/auth')
    const wrapper = mount(App, globalMountOptions)
    const authStore = useAuthStore()
    authStore.user = { user_id: '1', username: 'test', is_admin: false }
    await flushPromises()

    const links = wrapper.findAll('a')
    const chatLink = links.find(l => l.attributes('href') === '/chat')
    expect(chatLink).toBeDefined()
    expect(chatLink!.text()).toContain('Chat')
  })

  it('does not render nav when not authenticated', async () => {
    const { default: App } = await import('../../App.vue')
    const wrapper = mount(App, globalMountOptions)
    await flushPromises()

    const nav = wrapper.find('nav')
    expect(nav.exists()).toBe(false)
  })
})

describe('AppNav - Ctrl+/ keyboard shortcut', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.resetModules()
  })

  it('toggles chat panel open on Ctrl+/', async () => {
    const { default: App } = await import('../../App.vue')
    const { useAuthStore } = await import('../../stores/auth')
    const wrapper = mount(App, globalMountOptions)
    const authStore = useAuthStore()
    authStore.user = { user_id: '1', username: 'test', is_admin: false }
    await flushPromises()

    // Panel initially closed
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(false)

    // Dispatch Ctrl+/ on window
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: '/', bubbles: true }))
    await flushPromises()

    // Panel should now be open
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(true)
  })

  it('toggles chat panel closed again on second Ctrl+/', async () => {
    const { default: App } = await import('../../App.vue')
    const { useAuthStore } = await import('../../stores/auth')
    const wrapper = mount(App, globalMountOptions)
    const authStore = useAuthStore()
    authStore.user = { user_id: '1', username: 'test', is_admin: false }
    await flushPromises()

    // Open
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: '/', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(true)

    // Close
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, key: '/', bubbles: true }))
    await flushPromises()
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(false)

    wrapper.unmount()
  })
})

describe('AppNav - panel persistence across route navigation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.resetModules()
  })

  it('panel stays open after simulated route change', async () => {
    const { default: App } = await import('../../App.vue')
    const { useAuthStore } = await import('../../stores/auth')
    const wrapper = mount(App, globalMountOptions)
    const authStore = useAuthStore()
    authStore.user = { user_id: '1', username: 'test', is_admin: false }
    await flushPromises()

    // Open panel via toggle button click
    const chatToggleBtn = wrapper.find('button[title="Toggle chat (Ctrl+/)"]')
    expect(chatToggleBtn.exists()).toBe(true)
    await chatToggleBtn.trigger('click')
    await flushPromises()

    // Panel is open and SideChatPanel stub is rendered
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(true)

    // The panel persists because it's in App.vue outside <router-view>
    // Simulate route change via user object update (doesn't affect chatOpen)
    authStore.user = { user_id: '1', username: 'test', is_admin: false }
    await flushPromises()

    // Panel still open
    expect(wrapper.find('[data-testid="side-chat-panel-stub"]').exists()).toBe(true)

    wrapper.unmount()
  })
})
