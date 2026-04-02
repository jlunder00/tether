import { ref, watch } from 'vue'

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

  async function fetch() {
    const resp = await window.fetch(`/api/${parentType()}/${parentId()}/links`, { credentials: 'include' })
    links.value = resp.ok ? await resp.json() : []
  }

  async function create(url: string, label: string | null, category: string) {
    await window.fetch(`/api/${parentType()}/${parentId()}/links`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, label, category }),
    })
    await fetch()
  }

  async function remove(id: number) {
    await window.fetch(`/api/links/${id}`, { method: 'DELETE', credentials: 'include' })
    await fetch()
  }

  watch([parentType, parentId], () => fetch(), { immediate: true })

  return { links, fetch, create, remove }
}
