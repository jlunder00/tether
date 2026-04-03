import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../lib/api'

export interface FollowupConfig {
  enabled: boolean
  pre_ack_interval_min: number
  pre_ack_max_pings: number
  post_ack_interval_min: number
  post_ack_pings: number
}

export interface Anchor {
  id: string
  name: string
  time: string
  duration_minutes: number
  flexibility: string
  strictness: number
  color: string
  position: number
  followup_config: FollowupConfig | null
}

export const useAnchorStore = defineStore('anchors', () => {
  const anchors = ref<Anchor[]>([])

  async function fetchAnchors() {
    try {
      const resp = await api('/api/anchors')
      if (!resp.ok) throw new Error(`${resp.status}`)
      anchors.value = await resp.json()
    } catch (e) {
      console.error('fetchAnchors error:', e)
      anchors.value = []
    }
  }

  async function updateAnchor(anchor: Anchor) {
    const { id, ...body } = anchor
    await api(`/api/anchors/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    await fetchAnchors()
  }

  return { anchors, fetchAnchors, updateAnchor }
})
