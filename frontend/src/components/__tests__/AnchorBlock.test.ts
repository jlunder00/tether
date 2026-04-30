import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/' }),
}))

vi.mock('../../lib/api', () => ({
  api: vi.fn(() => Promise.resolve({ ok: true, json: async () => [] })),
}))

describe('AnchorBlock', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  async function mountBlock(props: Record<string, unknown> = {}) {
    const { default: AnchorBlock } = await import('../AnchorBlock.vue')
    return mount(AnchorBlock, {
      props: {
        anchorId: 'a1',
        anchorName: 'Morning',
        time: '08:00',
        color: '#fff',
        ...props,
      },
    })
  }

  it('renders an anchor dot', async () => {
    const w = await mountBlock()
    expect(w.find('[data-testid="anchor-dot"]').exists()).toBe(true)
  })

  it('applies anchor-dot--now class when isNow is true', async () => {
    const w = await mountBlock({ isNow: true })
    const dot = w.find('[data-testid="anchor-dot"]')
    expect(dot.classes()).toContain('anchor-dot--now')
  })

  it('applies anchor-dot--past class when isPast is true', async () => {
    const w = await mountBlock({ isPast: true })
    const dot = w.find('[data-testid="anchor-dot"]')
    expect(dot.classes()).toContain('anchor-dot--past')
  })

  it('hides the tether line when isLast is true', async () => {
    const w = await mountBlock({ isLast: true })
    expect(w.find('[data-testid="anchor-line"]').exists()).toBe(false)
  })

  it('shows the tether line when isLast is false', async () => {
    const w = await mountBlock({ isLast: false })
    expect(w.find('[data-testid="anchor-line"]').exists()).toBe(true)
  })
})
