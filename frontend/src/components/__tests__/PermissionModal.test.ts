import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PermissionModal from '../PermissionModal.vue'
import { useChatStore } from '../../stores/chat'
import { setBotTransport } from '../../composables/useBotTransport'
import { makeTransport } from '../../stores/__tests__/testHelpers'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/dashboard' }),
}))

function mountModal() {
  return mount(PermissionModal, { attachTo: document.body })
}

describe('PermissionModal', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    setBotTransport(makeTransport([]))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders nothing when pendingPermissionRequest is null', () => {
    const wrapper = mountModal()
    expect(document.body.textContent).not.toContain('Permission Request')
    wrapper.unmount()
  })

  it('renders when pendingPermissionRequest is set', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      summary: 'Tether wants to delete tasks',
      details: [],
    }
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('Permission Request')
    expect(document.body.textContent).toContain('Tether wants to delete tasks')
    wrapper.unmount()
  })

  it('shows summary text', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      summary: 'Allow reading calendar',
      details: [],
    }
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('Allow reading calendar')
    wrapper.unmount()
  })

  it('Show more details button toggles detail rows', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      summary: 'Summary',
      details: [{ label: 'File', value: '/etc/passwd' }],
    }
    await wrapper.vm.$nextTick()

    // Details hidden by default
    expect(document.body.textContent).not.toContain('/etc/passwd')

    // Click "Show more details"
    const showBtn = Array.from(document.querySelectorAll('button')).find(
      b => b.textContent?.includes('Show more details')
    )
    expect(showBtn).toBeDefined()
    showBtn!.click()
    await wrapper.vm.$nextTick()

    expect(document.body.textContent).toContain('/etc/passwd')
    wrapper.unmount()
  })

  it('Approve calls respondToPermission with approve: true', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    const spy = vi.spyOn(store, 'respondToPermission')
    store.pendingPermissionRequest = {
      request_id: 'req1',
      summary: 'Ok?',
      details: [],
    }
    await wrapper.vm.$nextTick()

    const approveBtn = Array.from(document.querySelectorAll('button')).find(
      b => b.textContent?.trim() === 'Approve'
    )
    expect(approveBtn).toBeDefined()
    approveBtn!.click()
    expect(spy).toHaveBeenCalledWith('req1', true)
    wrapper.unmount()
  })

  it('Deny calls respondToPermission with approve: false', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    const spy = vi.spyOn(store, 'respondToPermission')
    store.pendingPermissionRequest = {
      request_id: 'req1',
      summary: 'Ok?',
      details: [],
    }
    await wrapper.vm.$nextTick()

    const denyBtn = Array.from(document.querySelectorAll('button')).find(
      b => b.textContent?.trim() === 'Deny'
    )
    expect(denyBtn).toBeDefined()
    denyBtn!.click()
    expect(spy).toHaveBeenCalledWith('req1', false)
    wrapper.unmount()
  })

  it('60s timeout auto-denies if no response', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      const spy = vi.spyOn(store, 'respondToPermission')
      store.pendingPermissionRequest = {
        request_id: 'req-timeout',
        summary: 'Will you approve?',
        details: [],
      }
      await wrapper.vm.$nextTick()

      vi.advanceTimersByTime(60_000)
      expect(spy).toHaveBeenCalledWith('req-timeout', false)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('timer is cleared when Approve clicked (no double-deny after 60s)', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      const spy = vi.spyOn(store, 'respondToPermission')
      store.pendingPermissionRequest = {
        request_id: 'req1',
        summary: 'Ok?',
        details: [],
      }
      await wrapper.vm.$nextTick()

      const approveBtn = Array.from(document.querySelectorAll('button')).find(
        b => b.textContent?.trim() === 'Approve'
      )!
      approveBtn.click()
      // advance past timeout — should NOT fire again
      vi.advanceTimersByTime(60_000)
      expect(spy).toHaveBeenCalledTimes(1)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('timer is cleared when Deny clicked', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      const spy = vi.spyOn(store, 'respondToPermission')
      store.pendingPermissionRequest = {
        request_id: 'req1',
        summary: 'Ok?',
        details: [],
      }
      await wrapper.vm.$nextTick()

      const denyBtn = Array.from(document.querySelectorAll('button')).find(
        b => b.textContent?.trim() === 'Deny'
      )!
      denyBtn.click()
      vi.advanceTimersByTime(60_000)
      expect(spy).toHaveBeenCalledTimes(1)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('timer is cleared when pendingPermissionRequest becomes null', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      const spy = vi.spyOn(store, 'respondToPermission')
      store.pendingPermissionRequest = {
        request_id: 'req1',
        summary: 'Ok?',
        details: [],
      }
      await wrapper.vm.$nextTick()

      // Externally clear the request (e.g. session_ended)
      store.pendingPermissionRequest = null
      await wrapper.vm.$nextTick()

      vi.advanceTimersByTime(60_000)
      expect(spy).not.toHaveBeenCalled()
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
