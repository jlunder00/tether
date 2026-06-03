/**
 * Tests for index-based loading in useContextStore.
 *
 * Stream E: node_index endpoint for fast tree population.
 * Shapes as proposed by conversation-index-builder teammate.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useContextStore } from '../context'

vi.mock('../../lib/api', () => ({ api: vi.fn() }))

import { api } from '../../lib/api'
const mockApi = vi.mocked(api)

/** Shape returned by GET /api/nodes/index */
function makeNodeIndexItem(overrides = {}) {
  return {
    id: 'node-1',
    title: 'Test Node',
    parent_id: null as string | null,
    path: '/Test Node',
    child_count: 0,
    ...overrides,
  }
}

function mockResponse(data: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => data } as Response
}

describe('useContextStore — index-based loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockApi.mockReset()
  })

  describe('fetchNodesIndex()', () => {
    it('calls GET /api/nodes/index', async () => {
      mockApi.mockResolvedValue(mockResponse([]))
      const store = useContextStore()
      await store.fetchNodesIndex()
      expect(mockApi).toHaveBeenCalledWith('/api/nodes/index')
    })

    it('sets nodesIndexLoaded = true after successful fetch', async () => {
      mockApi.mockResolvedValue(mockResponse([makeNodeIndexItem()]))
      const store = useContextStore()
      expect(store.nodesIndexLoaded).toBe(false)
      await store.fetchNodesIndex()
      expect(store.nodesIndexLoaded).toBe(true)
    })

    it('populates nodes cache with index items', async () => {
      const items = [
        makeNodeIndexItem({ id: 'n1', title: 'Alpha', parent_id: null }),
        makeNodeIndexItem({ id: 'n2', title: 'Beta', parent_id: 'n1' }),
      ]
      mockApi.mockResolvedValue(mockResponse(items))
      const store = useContextStore()
      await store.fetchNodesIndex()

      expect(store.nodes['n1']).toBeTruthy()
      expect(store.nodes['n2']).toBeTruthy()
    })

    it('maps title → name in nodes cache', async () => {
      mockApi.mockResolvedValue(mockResponse([
        makeNodeIndexItem({ id: 'n1', title: 'My Project' }),
      ]))
      const store = useContextStore()
      await store.fetchNodesIndex()
      expect(store.nodes['n1'].name).toBe('My Project')
    })

    it('maps child_count → children_count in nodes cache', async () => {
      mockApi.mockResolvedValue(mockResponse([
        makeNodeIndexItem({ id: 'n1', child_count: 5 }),
      ]))
      const store = useContextStore()
      await store.fetchNodesIndex()
      expect(store.nodes['n1'].children_count).toBe(5)
    })

    it('rootNodes computed reflects index-loaded nodes', async () => {
      const items = [
        makeNodeIndexItem({ id: 'root-a', title: 'Root A', parent_id: null }),
        makeNodeIndexItem({ id: 'root-b', title: 'Root B', parent_id: null }),
        makeNodeIndexItem({ id: 'child-c', title: 'Child C', parent_id: 'root-a' }),
      ]
      mockApi.mockResolvedValue(mockResponse(items))
      const store = useContextStore()
      await store.fetchNodesIndex()

      const rootIds = store.rootNodes.map(n => n.id)
      expect(rootIds).toContain('root-a')
      expect(rootIds).toContain('root-b')
      expect(rootIds).not.toContain('child-c')
    })

    it('childrenOf() returns children from index', async () => {
      const items = [
        makeNodeIndexItem({ id: 'root-a', title: 'Root A', parent_id: null }),
        makeNodeIndexItem({ id: 'child-1', title: 'Child 1', parent_id: 'root-a' }),
        makeNodeIndexItem({ id: 'child-2', title: 'Child 2', parent_id: 'root-a' }),
      ]
      mockApi.mockResolvedValue(mockResponse(items))
      const store = useContextStore()
      await store.fetchNodesIndex()

      const children = store.childrenOf('root-a')
      expect(children).toHaveLength(2)
      expect(children.map(n => n.id)).toContain('child-1')
      expect(children.map(n => n.id)).toContain('child-2')
    })

    it('does not overwrite full ContextNode already in nodes cache', async () => {
      const store = useContextStore()
      // Simulate a full node already fetched (via fetchNode)
      store.nodes['n1'] = {
        id: 'n1', parent_id: null, name: 'Full Node', description: 'detailed',
        node_type: 'context', archived: false, target_date: null, status: 'active',
        status_override: true, color: '#ff0000', created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z', children_count: 3,
      }

      mockApi.mockResolvedValue(mockResponse([
        makeNodeIndexItem({ id: 'n1', title: 'Stale Index Name', child_count: 99 }),
      ]))
      await store.fetchNodesIndex()

      // Full details preserved
      expect(store.nodes['n1'].description).toBe('detailed')
      expect(store.nodes['n1'].status_override).toBe(true)
      expect(store.nodes['n1'].color).toBe('#ff0000')
    })

    it('nodesIndexLoaded stays false on fetch error', async () => {
      mockApi.mockResolvedValue(mockResponse(null, false, 500))
      const store = useContextStore()
      await store.fetchNodesIndex()
      expect(store.nodesIndexLoaded).toBe(false)
    })
  })
})
