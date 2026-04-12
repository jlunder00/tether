import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export interface KanbanColumn {
  id: string
  name: string
  position: number
  color: string | null
  match_rules: Record<string, unknown>
  entry_rules: Record<string, unknown>
  created_by: string | null
}

export const useKanbanStore = defineStore('kanban', () => {
  const columns = ref<KanbanColumn[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchColumns() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/kanban/columns')
      if (!resp.ok) throw new Error(`Failed to load columns (HTTP ${resp.status})`)
      const data = await resp.json()
      if (Array.isArray(data)) columns.value = data
    } catch (e) {
      console.error('fetchKanbanColumns error:', e)
      error.value = e instanceof Error ? e.message : 'Failed to load kanban columns'
      columns.value = []
    } finally {
      loading.value = false
    }
  }

  return { columns, loading, error, fetchColumns }
})
