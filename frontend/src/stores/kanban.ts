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

  async function fetchColumns() {
    loading.value = true
    try {
      const resp = await api('/api/kanban/columns')
      if (!resp.ok) throw new Error(`${resp.status}`)
      columns.value = await resp.json()
    } catch (e) {
      console.error('fetchKanbanColumns error:', e)
    } finally {
      loading.value = false
    }
  }

  return { columns, loading, fetchColumns }
})
