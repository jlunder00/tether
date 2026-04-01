import { defineStore } from 'pinia'
import { ref } from 'vue'

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
    const resp = await fetch('/api/anchors')
    anchors.value = await resp.json()
  }

  async function updateAnchor(anchor: Anchor) {
    const { id, ...body } = anchor
    await fetch(`/api/anchors/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    await fetchAnchors()
  }

  return { anchors, fetchAnchors, updateAnchor }
})
