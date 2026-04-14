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
  body: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useContextStore = defineStore('context', () => {
  /** Flat cache of all fetched nodes, keyed by id */
  const nodes = ref<Record<string, ContextNode>>({})

  /** Sections cache keyed by `${nodeId}::${sectionType}` */
  const sectionCache = ref<Record<string, NodeSection>>({})

  // -- Computed helpers ------------------------------------------------------

  const rootNodes = computed<ContextNode[]>(() =>
    Object.values(nodes.value)
      .filter(n => n.parent_id === null && !n.archived)
      .sort((a, b) => a.name.localeCompare(b.name))
  )

  const rootContextNodes = computed<ContextNode[]>(() =>
    rootNodes.value.filter(n => n.node_type === 'context')
  )

  function childrenOf(parentId: string): ContextNode[] {
    return Object.values(nodes.value)
      .filter(n => n.parent_id === parentId && !n.archived)
      .sort((a, b) => a.name.localeCompare(b.name))
  }

  function nodeByName(name: string, parentId: string | null = null): ContextNode | undefined {
    return Object.values(nodes.value).find(
      n => n.name === name && n.parent_id === parentId
    )
  }

  // -- API methods -----------------------------------------------------------

  async function fetchRootNodes(): Promise<ContextNode[]> {
    const resp = await api('/api/nodes')
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
    const resp = await api(`/api/nodes/${parentId}/children`)
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
    fields: Partial<Pick<ContextNode, 'name' | 'archived' | 'target_date' | 'status' | 'color'>>,
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

  async function fetchSections(nodeId: string): Promise<NodeSection[]> {
    const resp = await api(`/api/nodes/${nodeId}/sections`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchSections: ${resp.status} ${detail}`)
    }
    const data: NodeSection[] = await resp.json()
    for (const s of data) {
      sectionCache.value[`${nodeId}::${s.section_type}`] = s
    }
    return data
  }

  async function fetchSection(nodeId: string, sectionType: string): Promise<NodeSection | null> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}`)
    if (resp.status === 404) return null
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchSection: ${resp.status} ${detail}`)
    }
    const data: NodeSection = await resp.json()
    sectionCache.value[`${nodeId}::${sectionType}`] = data
    return data
  }

  async function saveSection(nodeId: string, sectionType: string, body: string): Promise<NodeSection> {
    const resp = await api(`/api/nodes/${nodeId}/sections/${encodeURIComponent(sectionType)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ body }),
    })
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`saveSection: ${resp.status} ${detail}`)
    }
    const data: NodeSection = await resp.json()
    sectionCache.value[`${nodeId}::${sectionType}`] = data
    return data
  }

  return {
    // State
    nodes,
    sectionCache,

    // Computed
    rootNodes,
    rootContextNodes,

    // Helpers
    childrenOf,
    nodeByName,

    // Node CRUD
    fetchRootNodes,
    fetchChildren,
    fetchNode,
    createNode,
    patchNode,
    deleteNode,
    moveNode,

    // Sections
    fetchSections,
    fetchSection,
    saveSection,
  }
})
