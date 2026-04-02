import { ref, watch } from 'vue'

export interface Dependency {
  id: number
  type: string      // the OTHER entity's type
  entity_id: string  // the OTHER entity's id
}

export interface Dependencies {
  blocks: Dependency[]
  blocked_by: Dependency[]
}

export function useDependencies(entityType: () => string, entityId: () => string) {
  const deps = ref<Dependencies>({ blocks: [], blocked_by: [] })

  async function fetch() {
    const resp = await window.fetch(`/api/${entityType()}/${entityId()}/dependencies`, { credentials: 'include' })
    deps.value = resp.ok ? await resp.json() : { blocks: [], blocked_by: [] }
  }

  async function add(blockerType: string, blockerId: string, blockedType: string, blockedId: string) {
    await window.fetch('/api/dependencies', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ blocker_type: blockerType, blocker_id: blockerId, blocked_type: blockedType, blocked_id: blockedId }),
    })
    await fetch()
  }

  async function remove(depId: number) {
    await window.fetch(`/api/dependencies/${depId}`, { method: 'DELETE', credentials: 'include' })
    await fetch()
  }

  watch([entityType, entityId], () => fetch(), { immediate: true })

  return { deps, fetch, add, remove }
}
