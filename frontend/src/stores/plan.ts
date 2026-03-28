import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface AnchorPlan { tasks: string[]; notes: string }
export interface DayPlan {
  date: string
  anchors: Record<string, AnchorPlan>
  acknowledgements: Record<string, string>
  check_in_log: unknown[]
}

export const usePlanStore = defineStore('plan', () => {
  const plan = ref<DayPlan | null>(null)
  const loading = ref(false)
  const _d = new Date()
  const today = `${_d.getFullYear()}-${String(_d.getMonth() + 1).padStart(2, '0')}-${String(_d.getDate()).padStart(2, '0')}`

  async function fetchPlan() {
    loading.value = true
    const resp = await fetch(`/api/plan/${today}`)
    plan.value = await resp.json()
    loading.value = false
  }

  async function updateAnchorTasks(anchorId: string, tasks: string[], notes: string) {
    if (!plan.value) return
    plan.value.anchors[anchorId] = { tasks, notes }
    await fetch(`/api/plan/${today}/anchors/${anchorId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasks, notes }),
    })
  }

  function connectWebSocket() {
    const ws = new WebSocket(`ws://${location.host}/ws`)
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'plan_updated') fetchPlan()
    }
    ws.onclose = () => setTimeout(connectWebSocket, 3000)
    return ws
  }

  return { plan, loading, today, fetchPlan, updateAnchorTasks, connectWebSocket }
})
