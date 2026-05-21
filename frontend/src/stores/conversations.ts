import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'
import type { ConversationDetail, ConversationMessage, MessagesPage } from '../types/conversations'

export const useConversationsStore = defineStore('conversations', () => {
  const list = ref<ConversationDetail[]>([])
  const selectedId = ref<string | null>(null)
  const messagesById = ref<Map<string, ConversationMessage[]>>(new Map())
  const hasMoreById = ref<Map<string, boolean>>(new Map())
  const loading = ref(false)
  const error = ref<string | null>(null)

  const selected = computed(() =>
    selectedId.value ? list.value.find(c => c.id === selectedId.value) ?? null : null
  )

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
    const res = await api('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'interactive', priority: 'normal', ...payload }),
    })
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

  async function loadMessages(id: string): Promise<void> {
    const res = await api(`/api/conversations/${id}/messages?limit=50`)
    if (!res.ok) return
    const page: MessagesPage = await res.json()
    // API returns newest-first; reverse for display (oldest-first)
    const newMap = new Map(messagesById.value)
    newMap.set(id, [...page.messages].reverse())
    messagesById.value = newMap
    const hasMoreMap = new Map(hasMoreById.value)
    hasMoreMap.set(id, page.has_more)
    hasMoreById.value = hasMoreMap
  }

  async function loadMessagesOlder(conversationId: string): Promise<void> {
    const current = messagesById.value.get(conversationId) ?? []
    if (!hasMoreById.value.get(conversationId)) return
    // Oldest message currently shown = current[0] (after reversing)
    // But API sorted newest-first, so oldest displayed = last received = current[0].id
    const beforeId = current[0]?.id
    if (!beforeId) return
    const qs = new URLSearchParams({ limit: '50', before_id: beforeId })
    const res = await api(`/api/conversations/${conversationId}/messages?${qs}`)
    if (!res.ok) return
    const page: MessagesPage = await res.json()
    const older = [...page.messages].reverse()
    const newMap = new Map(messagesById.value)
    newMap.set(conversationId, [...older, ...current])
    messagesById.value = newMap
    const hasMoreMap = new Map(hasMoreById.value)
    hasMoreMap.set(conversationId, page.has_more)
    hasMoreById.value = hasMoreMap
  }

  function appendMessage(conversationId: string, msg: ConversationMessage): void {
    const msgs = messagesById.value.get(conversationId) ?? []
    const newMap = new Map(messagesById.value)
    newMap.set(conversationId, [...msgs, msg])
    messagesById.value = newMap
  }

  return { list, selectedId, selected, messagesById, hasMoreById, loading, error, refresh, create, patch, select, loadMessages, loadMessagesOlder, appendMessage }
})
