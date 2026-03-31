import { defineStore } from 'pinia'
import { ref } from 'vue'

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'skipped' | 'blocked'

export interface FollowupConfig {
  enabled: boolean
  pre_ack_interval_min: number
  pre_ack_max_pings: number
  post_ack_interval_min: number
  post_ack_pings: number
}

export interface Task {
  id: string
  text: string
  status: TaskStatus
  position: number
  followup_config: FollowupConfig | null
  blocks: string[]
  blocked_by: string[]
}

export interface AnchorPlan { tasks: Task[]; notes: string }
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

  async function updateAnchorTasks(anchorId: string, tasks: Task[], notes: string) {
    if (!plan.value) return
    plan.value.anchors[anchorId] = { tasks, notes }
    const resp = await fetch(`/api/plan/${activeDate.value}/anchors/${anchorId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasks, notes }),
    })
    const data = await resp.json()
    if (data.tasks && plan.value.anchors[anchorId]) {
      plan.value.anchors[anchorId].tasks = data.tasks  // sync server-assigned UUIDs
    }
  }

  async function updateTaskStatus(taskId: string, status: TaskStatus) {
    await fetch(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    })
    if (!plan.value) return
    for (const anchor of Object.values(plan.value.anchors)) {
      const task = anchor.tasks.find(t => t.id === taskId)
      if (task) { task.status = status; break }
    }
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
    updateAnchorTasks, updateTaskStatus, connectWebSocket,
  }
})
