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

  function setMessages(id: string, msgs: ConversationMessage[]): void {
    messagesById.value = new Map(messagesById.value).set(id, msgs)
  }

  function setHasMore(id: string, value: boolean): void {
    hasMoreById.value = new Map(hasMoreById.value).set(id, value)
  }

  async function loadMessages(id: string): Promise<void> {
    const res = await api(`/api/conversations/${id}/messages?limit=50`)
    if (!res.ok) return
    const page: MessagesPage = await res.json()
    // API returns newest-first; reverse for display (oldest-first)
    setMessages(id, [...page.messages].reverse())
    setHasMore(id, page.has_more)
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
    const page: MessagesPage = await res.json()
    const older = [...page.messages].reverse()
    setMessages(conversationId, [...older, ...current])
    setHasMore(conversationId, page.has_more)
  }

  function appendMessage(conversationId: string, msg: ConversationMessage): void {
    const msgs = messagesById.value.get(conversationId) ?? []
    setMessages(conversationId, [...msgs, msg])
  }

  return { list, selectedId, selected, messagesById, hasMoreById, loading, error, refresh, create, patch, select, loadMessages, loadMessagesOlder, appendMessage }
})
