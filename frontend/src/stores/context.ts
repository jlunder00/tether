import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ContextNode {
  id: string
  parent_id: string | null
  name: string
  description: string | null
  node_type: 'context' | 'milestone'
  archived: boolean
  target_date: string | null
  status: string | null
  status_override: boolean
  color: string | null
  created_at: string
  updated_at: string
  // Only present when fetched via GET /api/nodes/{id} (single-node fetch)
  section_types?: string[]
  children_count?: number
}

export interface NodeSection {
  section_type: string
  name: string
  body: string
  position: number
  updated_at: string
}

export interface SectionFileInfo {
  name: string
  size: number
  position: number
  updated_at: string
}

export interface SectionTypeSummary {
  section_type: string
  file_count: number
}

// ---------------------------------------------------------------------------
// Internal index types (not exported — internal to store)
// ---------------------------------------------------------------------------

/** Lean item returned by GET /api/nodes/index */
interface NodeIndexItem {
  id: string
  title: string
  parent_id: string | null
  path: string
  child_count: number
}

/**
 * Returns true if a cached node has full data (from fetchNode/fetchRootNodes).
 * We detect "full" by the presence of `status_override` (boolean) which the
 * index stub intentionally omits.
 */
function isFullNode(node: ContextNode): boolean {
  return typeof (node as any).status_override === 'boolean'
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useContextStore = defineStore('context', () => {
  /** Flat cache of all fetched nodes, keyed by id */
  const nodes = ref<Record<string, ContextNode>>({})

  /** Sections cache keyed by `${nodeId}::${sectionType}::${name}` */
  const sectionCache = ref<Record<string, NodeSection>>({})

  /** Whether to include archived nodes in tree views */
  const showArchived = ref(false)

  /** True after a successful fetchNodesIndex() — tree expand doesn't need to re-fetch children */
  const nodesIndexLoaded = ref(false)

  // -- Computed helpers ------------------------------------------------------

  const rootNodes = computed<ContextNode[]>(() =>
    Object.values(nodes.value)
      .filter(n => n.parent_id === null && (showArchived.value || !n.archived))
      .sort((a, b) => a.name.localeCompare(b.name))
  )

  const rootContextNodes = computed<ContextNode[]>(() =>
    rootNodes.value.filter(n => n.node_type === 'context')
  )

  function childrenOf(parentId: string): ContextNode[] {
    return Object.values(nodes.value)
      .filter(n => n.parent_id === parentId && (showArchived.value || !n.archived))
      .sort((a, b) => a.name.localeCompare(b.name))
  }

  function nodeByName(name: string, parentId: string | null = null): ContextNode | undefined {
    return Object.values(nodes.value).find(
      n => n.name === name && n.parent_id === parentId
    )
  }

  // -- API methods -----------------------------------------------------------

  async function fetchRootNodes(): Promise<ContextNode[]> {
    const qs = showArchived.value ? '?include_archived=1' : ''
    const resp = await api(`/api/nodes${qs}`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchRootNodes: ${resp.status} ${detail}`)
    }
    const data: ContextNode[] = await resp.json()
    for (const node of data) {
      nodes.value[node.id] = node
    }
    return data
  }

  async function fetchChildren(parentId: string): Promise<ContextNode[]> {
    const qs = showArchived.value ? '?include_archived=1' : ''
    const resp = await api(`/api/nodes/${parentId}/children${qs}`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchChildren: ${resp.status} ${detail}`)
    }
    const data: ContextNode[] = await resp.json()
    for (const node of data) {
      nodes.value[node.id] = node
    }
    return data
  }

  async function fetchNode(nodeId: string): Promise<ContextNode> {
    const resp = await api(`/api/nodes/${nodeId}`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchNode: ${resp.status} ${detail}`)
    }
    const data: ContextNode = await resp.json()
    nodes.value[data.id] = data
    return data
  }

  async function createNode(
    parentId: string | null,
    name: string,
    nodeType: 'context' | 'milestone' = 'context',
    opts: { target_date?: string; status?: string; color?: string } = {},
  ): Promise<ContextNode> {
    const resp = await api('/api/nodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parent_id: parentId, name, node_type: nodeType, ...opts }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`createNode: ${resp.status} ${detail}`)
    }
    const data: ContextNode = await resp.json()
    nodes.value[data.id] = data
    return data
  }

  async function patchNode(
    nodeId: string,
    fields: Partial<Pick<ContextNode, 'name' | 'archived' | 'target_date' | 'status' | 'color' | 'description'>>,
  ): Promise<ContextNode> {
    const resp = await api(`/api/nodes/${nodeId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`patchNode: ${resp.status} ${detail}`)
    }
    const data: ContextNode = await resp.json()
    nodes.value[data.id] = data
    return data
  }

  async function deleteNode(nodeId: string): Promise<void> {
    const resp = await api(`/api/nodes/${nodeId}`, { method: 'DELETE' })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`deleteNode: ${resp.status} ${detail}`)
    }
    // Remove from cache recursively (node and all descendants)
    function collectDescendants(id: string): string[] {
      const children = Object.keys(nodes.value).filter(k => nodes.value[k].parent_id === id)
      return [id, ...children.flatMap(collectDescendants)]
    }
    const toRemove = collectDescendants(nodeId)
    for (const id of toRemove) {
      delete nodes.value[id]
    }
  }

  async function moveNode(nodeId: string, newParentId: string | null): Promise<void> {
    const resp = await api(`/api/nodes/${nodeId}/move`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_parent_id: newParentId }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`moveNode: ${resp.status} ${detail}`)
    }
    // Update cache: change the node's parent_id
    if (nodes.value[nodeId]) {
      nodes.value[nodeId].parent_id = newParentId
    }
  }

  async function fetchSections(nodeId: string): Promise<SectionTypeSummary[]> {
    const resp = await api(`/api/nodes/${nodeId}/sections`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchSections: ${resp.status} ${detail}`)
    }
    return await resp.json()
  }

  async function fetchSectionFiles(nodeId: string, sectionType: string): Promise<SectionFileInfo[]> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchSectionFiles: ${resp.status} ${detail}`)
    }
    return await resp.json()
  }

  async function fetchSection(nodeId: string, sectionType: string, name: string = 'main'): Promise<NodeSection | null> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}/${encodeURIComponent(name)}`)
    if (resp.status === 404) return null
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchSection: ${resp.status} ${detail}`)
    }
    const data: NodeSection = await resp.json()
    sectionCache.value[`${nodeId}::${sectionType}::${name}`] = data
    return data
  }

  async function saveSection(nodeId: string, sectionType: string, body: string, name: string = 'main'): Promise<NodeSection> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`saveSection: ${resp.status} ${detail}`)
    }
    const data: NodeSection = await resp.json()
    sectionCache.value[`${nodeId}::${sectionType}::${name}`] = data
    return data
  }

  async function createSectionFile(nodeId: string, sectionType: string, name: string, body: string = ''): Promise<NodeSection> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, body }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`createSectionFile: ${resp.status} ${detail}`)
    }
    const data: NodeSection = await resp.json()
    sectionCache.value[`${nodeId}::${sectionType}::${name}`] = data
    return data
  }

  async function deleteSectionFile(nodeId: string, sectionType: string, name: string): Promise<void> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`deleteSectionFile: ${resp.status} ${detail}`)
    }
    delete sectionCache.value[`${nodeId}::${sectionType}::${name}`]
  }

  /**
   * Load all nodes as lean index summaries.
   * Populates `nodes` cache without overwriting full ContextNode objects already cached.
   * After this, tree expand/collapse is instant (childrenOf() works from cache).
   */
  async function fetchNodesIndex(): Promise<void> {
    const resp = await api('/api/nodes/index')
    if (!resp.ok) return
    let items: NodeIndexItem[]
    try {
      items = await resp.json()
    } catch {
      return
    }
    for (const item of items) {
      const existing = nodes.value[item.id]
      if (existing && isFullNode(existing)) {
        // Full node already cached — update mutable display fields only
        existing.name = item.title
        existing.children_count = item.child_count
      } else if (existing) {
        // Index stub already there — refresh it
        existing.name = item.title
        existing.children_count = item.child_count
      } else {
        // New entry — insert as a lean stub with safe defaults
        nodes.value[item.id] = {
          id: item.id,
          parent_id: item.parent_id,
          name: item.title,
          description: null,
          node_type: 'context',
          archived: false,
          target_date: null,
          status: null,
          status_override: false,
          color: null,
          created_at: '',
          updated_at: '',
          children_count: item.child_count,
        }
      }
    }
    nodesIndexLoaded.value = true
  }

  return {
    // State
    nodes,
    sectionCache,
    showArchived,
    nodesIndexLoaded,

    // Computed
    rootNodes,
    rootContextNodes,

    // Helpers
    childrenOf,
    nodeByName,

    // Node CRUD
    fetchNodesIndex,
    fetchRootNodes,
    fetchChildren,
    fetchNode,
    createNode,
    patchNode,
    deleteNode,
    moveNode,

    // Sections
    fetchSections,
    fetchSectionFiles,
    fetchSection,
    saveSection,
    createSectionFile,
    deleteSectionFile,
  }
})
