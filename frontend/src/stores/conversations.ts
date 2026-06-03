import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'
import type { ConversationDetail, ConversationMessage, MessagesPage } from '../types/conversations'

/** Lean index item returned by GET /api/conversations/index */
interface ConversationIndexItem {
  id: string
  title: string
  parent_context_node_id: string | null
  updated_at: string
  message_count: number
}

export const useConversationsStore = defineStore('conversations', () => {
  const list = ref<ConversationDetail[]>([])
  const selectedId = ref<string | null>(null)
  const messagesById = ref<Map<string, ConversationMessage[]>>(new Map())
  const hasMoreById = ref<Map<string, boolean>>(new Map())
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** True after a successful refreshIndex() — sidebar tree can skip per-node expand fetches */
  const indexLoaded = ref(false)

  const selected = computed(() =>
    selectedId.value ? list.value.find(c => c.id === selectedId.value) ?? null : null
  )

  /**
   * Load all conversations as lean index summaries for fast initial tree population.
   *
   * Upserts into `list` by id — preserves full ConversationDetail objects already
   * cached (e.g. from fetchOne). New items use safe defaults for fields not included
   * in the index (state: 'open', priority: 'normal'). FolderCenterPanel calls
   * refreshForNode() in the background to upgrade these defaults with real state/priority.
   */
  async function refreshIndex(): Promise<void> {
    const res = await api('/api/conversations/index')
    if (!res.ok) return
    let items: ConversationIndexItem[]
    try {
      items = await res.json()
    } catch {
      return
    }
    for (const item of items) {
      const existing = list.value.find(c => c.id === item.id)
      if (existing) {
        // Preserve all fields not provided by the index (state, priority, is_system, etc.)
        existing.name = item.title
        existing.context_node_id = item.parent_context_node_id
        existing.last_message_at = item.updated_at
      } else {
        list.value.push({
          id: item.id,
          name: item.title,
          type: 'interactive',
          priority: 'normal',
          state: 'open',
          context_node_id: item.parent_context_node_id,
          thread_key: null,
          is_system: false,
          created_at: item.updated_at,
          last_message_at: item.updated_at,
          folder_name: null,
        })
      }
    }
    indexLoaded.value = true
  }

  /**
   * Silently upsert full ConversationDetail objects for a specific node into list.
   *
   * Used by FolderCenterPanel when index is already loaded: shows cached data
   * immediately (no spinner), then this call upgrades stubs with accurate
   * state/priority/folder_name without replacing the rest of the list.
   */
  async function refreshForNode(nodeId: string | null): Promise<void> {
    const qs = new URLSearchParams({ limit: '50', offset: '0' })
    if (nodeId) qs.set('context_node_id', nodeId)
    const res = await api(`/api/conversations?${qs}`)
    if (!res.ok) return
    let fresh: ConversationDetail[]
    try {
      fresh = await res.json()
    } catch {
      return
    }
    for (const conv of fresh) {
      const idx = list.value.findIndex(c => c.id === conv.id)
      if (idx !== -1) {
        list.value[idx] = conv
      } else {
        list.value.push(conv)
      }
    }
  }

  async function refresh(params?: { state?: string; context_node_id?: string }): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const qs = new URLSearchParams({ limit: '50', offset: '0' })
      if (params?.state) qs.set('state', params.state)
      if (params?.context_node_id) qs.set('context_node_id', params.context_node_id)
      const res = await api(`/api/conversations?${qs}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      list.value = await res.json()
    } catch (e) {
      error.value = String(e)
    } finally {
      loading.value = false
    }
  }

  async function create(payload: { name: string; type?: string; priority?: string; context_node_id?: string }): Promise<ConversationDetail | null> {
    // ── Optimistic insert: show immediately, reconcile with server response ──
    const tempId = `temp-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const now = new Date().toISOString()
    const tempConv: ConversationDetail = {
      id: tempId,
      name: payload.name,
      type: (payload.type as ConversationDetail['type']) ?? 'interactive',
      priority: (payload.priority as ConversationDetail['priority']) ?? 'normal',
      state: 'open',
      context_node_id: payload.context_node_id ?? null,
      thread_key: null,
      is_system: false,
      created_at: now,
      last_message_at: now,
      folder_name: null,
    }
    list.value.unshift(tempConv)

    const res = await api('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'interactive', priority: 'normal', ...payload }),
    })

    // Remove temp entry regardless of outcome (will be replaced by real or discarded)
    const tempIdx = list.value.findIndex(c => c.id === tempId)
    if (tempIdx !== -1) list.value.splice(tempIdx, 1)

    if (!res.ok) return null
    const conv: ConversationDetail = await res.json()
    list.value.unshift(conv)
    return conv
  }

  async function patch(id: string, fields: Partial<Pick<ConversationDetail, 'name' | 'priority' | 'context_node_id' | 'state'>>): Promise<boolean> {
    const res = await api(`/api/conversations/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    if (!res.ok) return false
    const idx = list.value.findIndex(c => c.id === id)
    if (idx !== -1) Object.assign(list.value[idx], fields)
    return true
  }

  function select(id: string | null): void {
    selectedId.value = id
    if (id && !messagesById.value.has(id)) {
      loadMessages(id)
    }
  }

  function setMessages(id: string, msgs: ConversationMessage[]): void {
    messagesById.value = new Map(messagesById.value).set(id, msgs)
  }

  function setHasMore(id: string, value: boolean): void {
    hasMoreById.value = new Map(hasMoreById.value).set(id, value)
  }

  async function loadMessages(id: string): Promise<void> {
    const res = await api(`/api/conversations/${id}/messages?limit=50`)
    if (!res.ok) return
    let page: MessagesPage
    try {
      page = await res.json()
    } catch (e) {
      // Non-JSON response (e.g. HTML from SPA fallback on infrastructure error).
      console.warn('[conversations] loadMessages: non-JSON response for', id, e)
      return
    }
    // API returns newest-first; reverse for display (oldest-first)
    setMessages(id, [...(page.messages ?? [])].reverse())
    setHasMore(id, page.has_more ?? false)
  }

  async function loadMessagesOlder(conversationId: string): Promise<void> {
    if (!hasMoreById.value.get(conversationId)) return
    const current = messagesById.value.get(conversationId) ?? []
    // Oldest message currently shown = current[0] (after reversing)
    const beforeId = current[0]?.id
    if (!beforeId) return
    const qs = new URLSearchParams({ limit: '50', before_id: beforeId })
    const res = await api(`/api/conversations/${conversationId}/messages?${qs}`)
    if (!res.ok) return
    let page: MessagesPage
    try {
      page = await res.json()
    } catch (e) {
      // Non-JSON response — preserve existing messages to avoid data loss.
      console.warn('[conversations] loadMessagesOlder: non-JSON response for', conversationId, e)
      return
    }
    const older = [...(page.messages ?? [])].reverse()
    setMessages(conversationId, [...older, ...current])
    setHasMore(conversationId, page.has_more ?? false)
  }

  function appendMessage(conversationId: string, msg: ConversationMessage): void {
    const msgs = messagesById.value.get(conversationId) ?? []
    setMessages(conversationId, [...msgs, msg])
  }

  /**
   * Discard a conversation: transitions state → 'rejected'.
   *
   * ⚠️  KNOWN DEBT — Option A implementation:
   * This call transitions conversation state to `rejected` but does NOT write a
   * `beacon_suppressions` row (the table doesn't exist yet — landing in
   * pool-builder's Beacon Phase 3 PR 1). When that PR merges, a follow-up PR
   * will upgrade this to call `POST /api/conversations/{id}/discard`, which
   * atomically writes state + suppression row. Until then, dismissals from this
   * period will not be recorded as suppressions; Beacon (when Phase 5 ships)
   * may re-dispatch the same checkpoint patterns the user already dismissed.
   *
   * TODO (Phase 5): replace with:
   *   const res = await api(`/api/conversations/${conversationId}/discard`, { method: 'POST' })
   *   if (!res.ok) return false
   *   const idx = list.value.findIndex(c => c.id === conversationId)
   *   if (idx !== -1) list.value[idx].state = 'rejected'
   *   return true
   */
  async function discard(conversationId: string): Promise<boolean> {
    return patch(conversationId, { state: 'rejected' })
  }

  async function assignNode(conversationId: string, nodeId: string | null): Promise<void> {
    const res = await api(`/api/conversations/${conversationId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context_node_id: nodeId }),
    })
    if (!res.ok) throw new Error(`assignNode: HTTP ${res.status}`)
    // Update local list in-place (avoids resetting active filter state)
    const idx = list.value.findIndex(c => c.id === conversationId)
    if (idx !== -1) list.value[idx].context_node_id = nodeId
  }

  /** Fetch a single conversation by id. Used for deep-link hydration when the
   *  conversation may not be in the paginated list (>50 conversations case). */
  async function fetchOne(conversationId: string): Promise<ConversationDetail | null> {
    const res = await api(`/api/conversations/${conversationId}`)
    if (!res.ok) return null
    const conv: ConversationDetail = await res.json()
    // Upsert into list so subsequent lookups by id work
    const idx = list.value.findIndex(c => c.id === conv.id)
    if (idx === -1) list.value.push(conv)
    else list.value[idx] = conv
    return conv
  }

  return {
    list, selectedId, selected, messagesById, hasMoreById, loading, error,
    indexLoaded, refreshIndex, refreshForNode, refresh,
    create, patch, discard, select,
    loadMessages, loadMessagesOlder, appendMessage,
    assignNode, fetchOne,
  }
})
