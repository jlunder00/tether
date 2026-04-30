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
  motif?: string | null
}

export type AnchorState = 'past' | 'now' | 'future'

/**
 * Pure helper — given a list of anchors and a reference time, returns a map of
 * anchorId → 'past' | 'now' | 'future'.
 *
 * Algorithm: sort by time, find the last anchor whose HH:MM ≤ now — that's "now".
 * Everything before it is "past", everything after is "future". If now is before
 * the first anchor, the first anchor is still "now" (no prior block active).
 */
export function computeAnchorStates(anchors: Anchor[], now: Date): Map<string, AnchorState> {
  const sorted = [...anchors].sort((a, b) => a.time.localeCompare(b.time))
  const nowMinutes = now.getHours() * 60 + now.getMinutes()

  let currentIndex = 0
  for (let i = 0; i < sorted.length; i++) {
    const [h, m] = sorted[i].time.split(':').map(Number)
    if (h * 60 + m <= nowMinutes) currentIndex = i
    else break
  }

  const result = new Map<string, AnchorState>()
  sorted.forEach((a, i) => {
    if (i < currentIndex) result.set(a.id, 'past')
    else if (i === currentIndex) result.set(a.id, 'now')
    else result.set(a.id, 'future')
  })
  return result
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

  async function createAnchor(anchor: Omit<Anchor, 'id'>) {
    await api('/api/anchors', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(anchor),
    })
    await fetchAnchors()
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

  async function deleteAnchor(anchorId: string) {
    await api(`/api/anchors/${anchorId}`, { method: 'DELETE' })
    await fetchAnchors()
  }

  return { anchors, fetchAnchors, createAnchor, updateAnchor, deleteAnchor }
})
