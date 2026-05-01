import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'
import type { ApiKey, ApiKeyCreated } from '../types/apiKeys'

export const useApiKeysStore = defineStore('apiKeys', () => {
  const keys = ref<ApiKey[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const createdKey = ref<ApiKeyCreated | null>(null)

  async function fetchKeys() {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/keys')
      if (resp.ok) {
        keys.value = await resp.json()
      } else {
        error.value = 'Failed to load API keys.'
      }
    } catch {
      error.value = 'Could not reach server. Check your connection.'
    } finally {
      loading.value = false
    }
  }

  async function createKey(name: string) {
    loading.value = true
    error.value = null
    try {
      const resp = await api('/api/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      if (resp.ok) {
        const data: ApiKeyCreated = await resp.json()
        createdKey.value = data
        // Add to keys list (without raw_key)
        const { raw_key: _raw, ...keyData } = data
        keys.value = [...keys.value, keyData as ApiKey]
      } else {
        error.value = 'Failed to create API key.'
      }
    } catch {
      error.value = 'Could not reach server. Check your connection.'
    } finally {
      loading.value = false
    }
  }

  async function revokeKey(id: string) {
    loading.value = true
    error.value = null
    try {
      const resp = await api(`/api/keys/${id}`, { method: 'DELETE' })
      if (resp.ok) {
        keys.value = keys.value.filter(k => k.id !== id)
      } else {
        error.value = 'Failed to revoke API key.'
      }
    } catch {
      error.value = 'Could not reach server. Check your connection.'
    } finally {
      loading.value = false
    }
  }

  function clearCreatedKey() {
    createdKey.value = null
  }

  return {
    keys,
    loading,
    error,
    createdKey,
    fetchKeys,
    createKey,
    revokeKey,
    clearCreatedKey,
  }
})
