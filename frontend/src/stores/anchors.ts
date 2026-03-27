import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Anchor {
  id: string
  name: string
  time: string
  duration_minutes: number
  flexibility: string
  strictness: number
  color: string
  position: number
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
