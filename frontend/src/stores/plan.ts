import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface AnchorPlan { tasks: string[]; notes: string }
export interface DayPlan {
  date: string
  anchors: Record<string, AnchorPlan>
  acknowledgements: Record<string, string>
  check_in_log: unknown[]
}

function localDateString(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function offsetDate(base: string, days: number): string {
  const d = new Date(base + 'T12:00:00') // noon to avoid DST edge cases
  d.setDate(d.getDate() + days)
  return localDateString(d)
}

export const usePlanStore = defineStore('plan', () => {
  const plan = ref<DayPlan | null>(null)
  const loading = ref(false)
  const today = localDateString(new Date())
  const activeDate = ref(today)
  const savedDates = ref<string[]>([])

  async function fetchPlan(date?: string) {
    if (date) activeDate.value = date
    loading.value = true
    const resp = await fetch(`/api/plan/${activeDate.value}`)
    plan.value = await resp.json()
    loading.value = false
  }

  async function fetchSavedDates() {
    const resp = await fetch('/api/plans')
    savedDates.value = await resp.json()
  }

  function goToPrevDay() { fetchPlan(offsetDate(activeDate.value, -1)) }
  function goToNextDay() { fetchPlan(offsetDate(activeDate.value, +1)) }
  function goToToday()   { fetchPlan(today) }

  async function updateAnchorTasks(anchorId: string, tasks: string[], notes: string) {
    if (!plan.value) return
    plan.value.anchors[anchorId] = { tasks, notes }
    await fetch(`/api/plan/${activeDate.value}/anchors/${anchorId}`, {
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

  return {
    plan, loading, today, activeDate, savedDates,
    fetchPlan, fetchSavedDates,
    goToPrevDay, goToNextDay, goToToday,
    updateAnchorTasks, connectWebSocket,
  }
})
