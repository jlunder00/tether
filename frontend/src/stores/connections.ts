import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'
import { useAuthStore } from './auth'
import type { Connection } from '../types/connections'

export const useConnectionsStore = defineStore('connections', () => {
  const connections = ref<Connection[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  function myUserId(): string | undefined {
    return useAuthStore().user?.user_id
  }

  const pending_incoming = computed(() => {
    const me = myUserId()
    return connections.value.filter(
      c => c.status === 'pending' && c.initiated_by !== me,
    )
  })

  const pending_outgoing = computed(() => {
    const me = myUserId()
    return connections.value.filter(
      c => c.status === 'pending' && c.initiated_by === me,
    )
  })

  const accepted = computed(() =>
    connections.value.filter(c => c.status === 'accepted'),
  )

  async function fetchConnections() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/connections')
      if (resp.ok) {
        connections.value = await resp.json()
      } else {
        error.value = 'Failed to load connections.'
      }
    } catch {
      error.value = 'Could not reach server. Check your connection.'
    } finally {
      loading.value = false
    }
  }

  async function sendRequest(username: string) {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/connections/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_username: username }),
      })
      if (resp.ok) {
        const conn: Connection = await resp.json()
        connections.value = [...connections.value, conn]
      } else {
        const data = await resp.json().catch(() => ({}))
        error.value = (data as any).detail || 'Failed to send request.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  async function acceptConnection(id: number) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/connections/${id}/accept`, { method: 'POST' })
      if (resp.ok) {
        const patch: { id: number; status: string } = await resp.json()
        connections.value = connections.value.map(c =>
          c.id === id ? { ...c, status: patch.status as Connection['status'] } : c,
        )
      } else {
        error.value = 'Failed to accept connection.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  async function declineConnection(id: number, block = false) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/connections/${id}/decline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block }),
      })
      if (resp.ok) {
        const data: any = await resp.json()
        if (data.deleted) {
          connections.value = connections.value.filter(c => c.id !== id)
        } else if (data.status) {
          connections.value = connections.value.map(c =>
            c.id === id ? { ...c, status: data.status as Connection['status'] } : c,
          )
        }
      } else {
        error.value = 'Failed to decline connection.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  async function toggleAutoSchedule(id: number, value: boolean) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/connections/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_schedule: value }),
      })
      if (resp.ok) {
        const updated: Connection = await resp.json()
        connections.value = connections.value.map(c =>
          c.id === id ? { ...c, ...updated } : c,
        )
      } else {
        error.value = 'Failed to update setting.'
      }
    } catch {
      error.value = 'Could not reach server.'
    } finally {
      loading.value = false
    }
  }

  return {
    connections,
    loading,
    error,
    pending_incoming,
    pending_outgoing,
    accepted,
    fetchConnections,
    sendRequest,
    acceptConnection,
    declineConnection,
    toggleAutoSchedule,
  }
})
