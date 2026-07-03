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
      kind: 'destructive',
      target: 'tasks/2024-01-15',
      reason_from_bot: null,
    }
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('Permission Request')
    expect(document.body.textContent).toContain('tasks/2024-01-15')
    wrapper.unmount()
  })

  it('shows kind label and target', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'read_out_of_scope',
      target: '/calendar/events',
      reason_from_bot: null,
    }
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('Read out-of-scope content')
    expect(document.body.textContent).toContain('/calendar/events')
    wrapper.unmount()
  })

  it('Show reason button toggles reason text', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'user_section_edit',
      target: 'section/work',
      reason_from_bot: 'Need to update your work section with new tasks.',
    }
    await wrapper.vm.$nextTick()

    // Reason hidden by default
    expect(document.body.textContent).not.toContain('Need to update your work section')

    // Click "Show reason"
    const showBtn = Array.from(document.querySelectorAll('button')).find(
      b => b.textContent?.includes('Show reason')
    )
    expect(showBtn).toBeDefined()
    showBtn!.click()
    await wrapper.vm.$nextTick()

    expect(document.body.textContent).toContain('Need to update your work section')
    wrapper.unmount()
  })

  it('does not show reason button when reason_from_bot is null', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'destructive',
      target: 'tasks/old',
      reason_from_bot: null,
    }
    await wrapper.vm.$nextTick()

    const showBtn = Array.from(document.querySelectorAll('button')).find(
      b => b.textContent?.includes('Show reason')
    )
    expect(showBtn).toBeUndefined()
    wrapper.unmount()
  })

  it('Approve calls respondToPermission with approve: true', async () => {
    const wrapper = mountModal()
    const store = useChatStore()
    const spy = vi.spyOn(store, 'respondToPermission')
    store.pendingPermissionRequest = {
      request_id: 'req1',
      kind: 'destructive',
      target: 'tasks/old',
      reason_from_bot: null,
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
      kind: 'destructive',
      target: 'tasks/old',
      reason_from_bot: null,
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

  it('60s timeout dismisses modal to waiting indicator without auto-denying', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      const spy = vi.spyOn(store, 'respondToPermission')
      store.pendingPermissionRequest = {
        request_id: 'req-timeout',
        kind: 'destructive',
        target: 'tasks/all',
        reason_from_bot: null,
      }
      await wrapper.vm.$nextTick()

      // Before timeout: full modal visible
      expect(document.body.textContent).toContain('Permission Request')

      vi.advanceTimersByTime(60_000)
      await wrapper.vm.$nextTick()

      // After timeout: modal dismissed — NO auto-deny; backend is the authority
      expect(spy).not.toHaveBeenCalled()

      // Compact waiting indicator should appear instead
      expect(document.body.textContent).toContain('Waiting on your response')

      // Full modal should be gone
      expect(document.body.textContent).not.toContain('Permission Request')

      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('after dismiss, new pendingPermissionRequest resets to full modal', async () => {
    // Verifies that the dismissed state resets when a new permission_request arrives.
    // This covers the case where the user responds via the backend's session_timeout
    // (clears the request) and then a new session starts with a fresh request.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      const wrapper = mountModal()
      const store = useChatStore()
      store.pendingPermissionRequest = {
        request_id: 'req-first',
        kind: 'destructive',
        target: 'tasks/all',
        reason_from_bot: null,
      }
      await wrapper.vm.$nextTick()
      vi.advanceTimersByTime(60_000)
      await wrapper.vm.$nextTick()

      // Modal is now dismissed → waiting indicator
      expect(document.body.textContent).toContain('Waiting on your response')

      // New request arrives (e.g. user sends another message, new session)
      store.pendingPermissionRequest = {
        request_id: 'req-second',
        kind: 'user_section_edit',
        target: 'section/work',
        reason_from_bot: null,
      }
      await wrapper.vm.$nextTick()

      // Full modal should reappear for the new request
      expect(document.body.textContent).toContain('Permission Request')
      expect(document.body.textContent).not.toContain('Waiting on your response')
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
        kind: 'destructive',
        target: 'tasks/old',
        reason_from_bot: null,
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
        kind: 'destructive',
        target: 'tasks/old',
        reason_from_bot: null,
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
        kind: 'destructive',
        target: 'tasks/old',
        reason_from_bot: null,
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
