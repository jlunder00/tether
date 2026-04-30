import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import AnchorFocusWidget from '../AnchorFocusWidget.vue'
import { useAnchorStore } from '../../stores/anchors'

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

/**
 * Build three anchors bracketing the real current time so no fake timers
 * are needed. We place one 2 h before now, one 1 h before now (= "now"),
 * and one 1 h after now. Edge-case: clamp to [00,23].
 */
function makeRealTimeAnchors() {
  const h = new Date().getHours()
  const fmt = (n: number) => `${String(Math.min(23, Math.max(0, n))).padStart(2, '0')}:00`
  return [
    { id: 'a-prev', name: 'Morning',   time: fmt(h - 2), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#aaa', position: 0, followup_config: null, motif: null },
    { id: 'a-now',  name: 'Deep Work', time: fmt(h - 1), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#bbb', position: 1, followup_config: null, motif: null },
    { id: 'a-next', name: 'Wind Down', time: fmt(h + 1), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#ccc', position: 2, followup_config: null, motif: null },
  ]
}

describe('AnchorFocusWidget', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountWidget(anchors = makeRealTimeAnchors()) {
    const store = useAnchorStore()
    store.anchors = anchors as typeof store.anchors
    const wrapper = mount(AnchorFocusWidget)
    await nextTick()
    return wrapper
  }

  it('shows current anchor name when it is the active block', async () => {
    const w = await mountWidget()
    const current = w.find('[data-testid="anchor-focus-current"]')
    expect(current.exists()).toBe(true)
    expect(current.text()).toContain('Deep Work')
  })

  it('shows prev anchor at reduced opacity', async () => {
    const w = await mountWidget()
    const prev = w.find('[data-testid="anchor-focus-prev"]')
    expect(prev.exists()).toBe(true)
    expect(prev.text()).toContain('Morning')
    expect(prev.classes()).toContain('anchor-focus-row--subdued')
  })

  it('shows next anchor at reduced opacity', async () => {
    const w = await mountWidget()
    const next = w.find('[data-testid="anchor-focus-next"]')
    expect(next.exists()).toBe(true)
    expect(next.text()).toContain('Wind Down')
    expect(next.classes()).toContain('anchor-focus-row--subdued')
  })

  it('does not show prev when first anchor is current', async () => {
    const h = new Date().getHours()
    const fmt = (n: number) => `${String(Math.min(23, Math.max(0, n))).padStart(2, '0')}:00`
    // Only two anchors: current (before now) + next (after now) — no prior anchor
    const anchors = [
      { id: 'a-now',  name: 'First Block', time: fmt(h - 1), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#bbb', position: 0, followup_config: null, motif: null },
      { id: 'a-next', name: 'Next Block',  time: fmt(h + 1), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#ccc', position: 1, followup_config: null, motif: null },
    ]
    const w = await mountWidget(anchors)
    expect(w.find('[data-testid="anchor-focus-prev"]').exists()).toBe(false)
    expect(w.find('[data-testid="anchor-focus-current"]').text()).toContain('First Block')
  })

  it('does not show next when last anchor is current', async () => {
    const h = new Date().getHours()
    const fmt = (n: number) => `${String(Math.min(23, Math.max(0, n))).padStart(2, '0')}:00`
    // Only two anchors: prev (before now) + current (before now, last) — no future anchor
    const anchors = [
      { id: 'a-prev', name: 'Prev Block', time: fmt(h - 2), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#aaa', position: 0, followup_config: null, motif: null },
      { id: 'a-now',  name: 'Last Block', time: fmt(h - 1), duration_minutes: 60, flexibility: 'flexible', strictness: 1, color: '#bbb', position: 1, followup_config: null, motif: null },
    ]
    const w = await mountWidget(anchors)
    expect(w.find('[data-testid="anchor-focus-next"]').exists()).toBe(false)
    expect(w.find('[data-testid="anchor-focus-current"]').text()).toContain('Last Block')
  })
})
