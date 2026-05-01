import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { ApiKey, ApiKeyCreated } from '../../types/apiKeys'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ path: '/settings' }),
}))

vi.mock('../../stores/apiKeys', () => ({
  useApiKeysStore: vi.fn(),
}))

import { useApiKeysStore } from '../../stores/apiKeys'

function makeStore(overrides: Partial<{
  keys: ApiKey[]
  loading: boolean
  error: string | null
  createdKey: ApiKeyCreated | null
  fetchKeys: () => Promise<void>
  createKey: (name: string) => Promise<void>
  revokeKey: (id: string) => Promise<void>
  clearCreatedKey: () => void
}> = {}) {
  return {
    keys: [],
    loading: false,
    error: null,
    createdKey: null,
    fetchKeys: vi.fn().mockResolvedValue(undefined),
    createKey: vi.fn().mockResolvedValue(undefined),
    revokeKey: vi.fn().mockResolvedValue(undefined),
    clearCreatedKey: vi.fn(),
    ...overrides,
  }
}

const sampleKey: ApiKey = {
  id: 'key1',
  name: 'My MCP Key',
  key_prefix: 'ttr_abcd',
  created_at: '2026-01-01T00:00:00Z',
  last_used_at: '2026-04-01T00:00:00Z',
  revoked_at: null,
}

const revokedKey: ApiKey = {
  id: 'key2',
  name: 'Old Key',
  key_prefix: 'ttr_efgh',
  created_at: '2025-06-01T00:00:00Z',
  last_used_at: null,
  revoked_at: '2025-12-01T00:00:00Z',
}

describe('ApiKeysSection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore() as any)
  })

  it('mounts without error', async () => {
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    expect(wrapper.exists()).toBe(true)
  })

  it('shows empty state when keys is empty', async () => {
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ keys: [] }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    expect(wrapper.text()).toContain('No API keys yet')
  })

  it('shows key list when keys has items', async () => {
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ keys: [sampleKey] }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    const row = wrapper.find('[data-testid="apikeys-key-key1"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('My MCP Key')
    expect(row.text()).toContain('ttr_abcd')
  })

  it('revoked key shows Revoked badge not revoke button', async () => {
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ keys: [revokedKey] }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    const row = wrapper.find('[data-testid="apikeys-key-key2"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('Revoked')
    expect(wrapper.find('[data-testid="apikeys-revoke-key2"]').exists()).toBe(false)
  })

  it('revoke button click shows inline confirmation', async () => {
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ keys: [sampleKey] }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    await wrapper.find('[data-testid="apikeys-revoke-key1"]').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="apikeys-revoke-confirm-key1"]').exists()).toBe(true)
  })

  it('confirm revoke calls store.revokeKey(id)', async () => {
    const revokeKey = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ keys: [sampleKey], revokeKey }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    await wrapper.find('[data-testid="apikeys-revoke-key1"]').trigger('click')
    await wrapper.vm.$nextTick()
    await wrapper.find('[data-testid="apikeys-revoke-confirm-key1"]').trigger('click')
    expect(revokeKey).toHaveBeenCalledWith('key1')
  })

  it('create form submit calls store.createKey(name)', async () => {
    const createKey = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ createKey }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    await wrapper.find('[data-testid="apikeys-create-input"]').setValue('My New Key')
    await wrapper.find('[data-testid="apikeys-create-submit"]').trigger('click')
    expect(createKey).toHaveBeenCalledWith('My New Key')
  })

  it('raw key panel shown when createdKey is set', async () => {
    const createdKey: ApiKeyCreated = {
      ...sampleKey,
      raw_key: 'ttr_abcd_supersecretvalue',
    }
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ createdKey }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    const codeEl = wrapper.find('[data-testid="apikeys-raw-key"]')
    expect(codeEl.exists()).toBe(true)
    expect(codeEl.text()).toContain('ttr_abcd_supersecretvalue')
  })

  it('done button calls store.clearCreatedKey()', async () => {
    const clearCreatedKey = vi.fn()
    const createdKey: ApiKeyCreated = {
      ...sampleKey,
      raw_key: 'ttr_abcd_supersecretvalue',
    }
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ createdKey, clearCreatedKey }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    const wrapper = mount(ApiKeysSection)
    await wrapper.find('[data-testid="apikeys-done-btn"]').trigger('click')
    expect(clearCreatedKey).toHaveBeenCalledOnce()
  })

  it('calls store.fetchKeys() on mount', async () => {
    const fetchKeys = vi.fn().mockResolvedValue(undefined)
    vi.mocked(useApiKeysStore).mockReturnValue(makeStore({ fetchKeys }) as any)
    const { default: ApiKeysSection } = await import('../ApiKeysSection.vue')
    mount(ApiKeysSection)
    expect(fetchKeys).toHaveBeenCalledOnce()
  })
})
