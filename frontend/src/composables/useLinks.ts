import { ref, watch } from 'vue'
import { api } from '../lib/api'

export interface Link {
  id: number
  parent_type: string
  parent_id: string
  url: string
  label: string | null
  category: string
  created_at: string
}

export function useLinks(parentType: () => string, parentId: () => string) {
  const links = ref<Link[]>([])

  async function load() {
    const resp = await api(`/api/${parentType()}/${parentId()}/links`)
    links.value = resp.ok ? await resp.json() : []
  }

  async function create(url: string, label: string | null, category: string) {
    await api(`/api/${parentType()}/${parentId()}/links`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, label, category }),
    })
    await load()
  }

  async function remove(id: number) {
    await api(`/api/links/${id}`, { method: 'DELETE' })
    await load()
  }

  watch([parentType, parentId], () => load(), { immediate: true })

  return { links, load, create, remove }
}
