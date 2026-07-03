import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DEFAULT_ROUTING = {
  anchor_ping: { mode: 'thread_by_key', priority: 'important', external: ['telegram'], key_template: 'anchor:{anchor_id}:{date}' },
  task_followup: { mode: 'thread_by_key', priority: 'important', external: ['telegram'], key_template: 'anchor:{anchor_id}:{date}' },
  beacon: { mode: 'bot_decides', priority: 'normal', external: ['web'] },
  meeting_event: { mode: 'thread_by_key', priority: 'important', external: ['telegram', 'web'], key_template: 'meeting:{request_id}' },
  scheduling_update: { mode: 'fixed', priority: 'normal', external: ['web'] },
}

function mockApiGet(routing = DEFAULT_ROUTING) {
  vi.mocked(api).mockResolvedValue({
    ok: true,
    json: async () => ({ theme: null, mode: null, notification_routing: routing }),
  } as Response)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('NotificationRoutingSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders a row for each of the 5 notification types', async () => {
    mockApiGet()
    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const rows = wrapper.findAll('[data-notif-type]')
    expect(rows).toHaveLength(5)
    const types = rows.map(r => r.attributes('data-notif-type'))
    expect(types).toContain('anchor_ping')
    expect(types).toContain('task_followup')
    expect(types).toContain('beacon')
    expect(types).toContain('meeting_event')
    expect(types).toContain('scheduling_update')
  })

  it('shows routing mode dropdown for each type', async () => {
    mockApiGet()
    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const modeSelects = wrapper.findAll('[data-mode-select]')
    expect(modeSelects.length).toBe(5)
  })

  it('shows priority selector for each type', async () => {
    mockApiGet()
    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const prioritySelects = wrapper.findAll('[data-priority-select]')
    expect(prioritySelects.length).toBe(5)
  })

  it('web channel checkbox is always checked and disabled', async () => {
    mockApiGet()
    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const webCheckboxes = wrapper.findAll('[data-channel="web"]')
    expect(webCheckboxes.length).toBeGreaterThan(0)
    for (const cb of webCheckboxes) {
      expect((cb.element as HTMLInputElement).disabled).toBe(true)
      expect((cb.element as HTMLInputElement).checked).toBe(true)
    }
  })

  it('discord and slack checkboxes are disabled ("coming soon")', async () => {
    mockApiGet()
    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    for (const channel of ['discord', 'slack']) {
      const cbs = wrapper.findAll(`[data-channel="${channel}"]`)
      for (const cb of cbs) {
        expect((cb.element as HTMLInputElement).disabled).toBe(true)
      }
    }
  })

  it('toggling telegram checkbox calls PATCH with updated external list', async () => {
    // First call = GET (mount), second call = PATCH (toggle)
    vi.mocked(api)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ theme: null, mode: null, notification_routing: DEFAULT_ROUTING }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as Response)

    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    // Find telegram checkbox in anchor_ping row (it's checked by default)
    const anchorRow = wrapper.find('[data-notif-type="anchor_ping"]')
    const telegramCb = anchorRow.find('[data-channel="telegram"]')
    expect(telegramCb.exists()).toBe(true)

    // Uncheck the element and fire change — Vue Test Utils doesn't auto-toggle on synthetic events
    ;(telegramCb.element as HTMLInputElement).checked = false
    await telegramCb.trigger('change')

    // Second call should be PATCH
    expect(vi.mocked(api)).toHaveBeenCalledTimes(2)
    const patchCall = vi.mocked(api).mock.calls[1]
    expect(patchCall[0]).toBe('/api/user/preferences')
    expect((patchCall[1] as RequestInit).method).toBe('PATCH')
    const body = JSON.parse((patchCall[1] as RequestInit).body as string)
    // Telegram was toggled off for anchor_ping
    expect(body.notification_routing.anchor_ping.external).not.toContain('telegram')
  })

  it('changing routing mode calls PATCH with updated mode', async () => {
    vi.mocked(api)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ theme: null, mode: null, notification_routing: DEFAULT_ROUTING }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      } as Response)

    const { default: NotificationRoutingSection } = await import('../NotificationRoutingSection.vue')
    const wrapper = mount(NotificationRoutingSection)
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const beaconRow = wrapper.find('[data-notif-type="beacon"]')
    const modeSelect = beaconRow.find('[data-mode-select]')
    await modeSelect.setValue('new_each')

    expect(vi.mocked(api)).toHaveBeenCalledTimes(2)
    const patchCall = vi.mocked(api).mock.calls[1]
    const body = JSON.parse((patchCall[1] as RequestInit).body as string)
    expect(body.notification_routing.beacon.mode).toBe('new_each')
  })
})
