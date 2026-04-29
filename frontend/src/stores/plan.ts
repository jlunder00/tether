import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { FollowupConfig } from './anchors'
import { api } from '../lib/api'

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'skipped' | 'blocked'

export type { FollowupConfig }

export interface Task {
  id: string
  text: string
  description: string | null
  status: TaskStatus
  position: number
  followup_config: FollowupConfig | null
  blocks: string[]
  blocked_by: string[]
  context_subject: string | null
  context_node_id: string | null
  // Scheduling timestamps (set when task is promoted to a calendar event)
  start_time?: string | null
  end_time?: string | null
  // Anchor association — set for plan tasks; null for backlog
  anchor_id?: string | null
  // Recurrence fields — anchor-recurring tasks only
  rrule?: string | null
  is_recurring_master?: boolean
  original_date?: string
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
  const plans = ref<Record<string, DayPlan>>({})

  async function fetchPlan(date?: string) {
    if (date) activeDate.value = date
    loading.value = true
    try {
      const resp = await api(`/api/plan/${activeDate.value}`)
      if (!resp.ok) throw new Error(`${resp.status}`)
      plan.value = await resp.json()
    } catch (e) {
      console.error('fetchPlan error:', e)
      plan.value = null
    } finally {
      loading.value = false
    }
  }

  async function fetchSavedDates() {
    const resp = await api('/api/plans')
    savedDates.value = await resp.json()
  }

  function goToPrevDay() { fetchPlan(offsetDate(activeDate.value, -1)) }
  function goToNextDay() { fetchPlan(offsetDate(activeDate.value, +1)) }
  function goToToday()   { fetchPlan(today) }

  async function fetchPlanRange(startDate: string, endDate: string) {
    const resp = await api(`/api/plan/range?start=${startDate}&end=${endDate}`)
    const data: Record<string, DayPlan> = await resp.json()
    plans.value = { ...plans.value, ...data }
  }

  async function moveTask(
    taskUuid: string,
    fromDate: string, fromAnchor: string,
    toDate: string, toAnchor: string,
    position?: number,
  ) {
    // Optimistic update in plans cache
    const fromDay = plans.value[fromDate] ?? (fromDate === activeDate.value ? plan.value : null)
    const toDay = plans.value[toDate] ?? (toDate === activeDate.value ? plan.value : null)
    if (fromDay && toDay) {
      const task = fromDay.anchors[fromAnchor]?.tasks.find(t => t.id === taskUuid)
      if (task) {
        fromDay.anchors[fromAnchor].tasks = fromDay.anchors[fromAnchor].tasks.filter(t => t.id !== taskUuid)
        if (!toDay.anchors[toAnchor]) toDay.anchors[toAnchor] = { tasks: [], notes: '' }
        const pos = position ?? toDay.anchors[toAnchor].tasks.length
        toDay.anchors[toAnchor].tasks.splice(pos, 0, { ...task, position: pos })
      }
    }
    await api(`/api/tasks/${taskUuid}/move`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: toDate, anchor_id: toAnchor, position }),
    })
  }

  async function reorderTask(taskUuid: string, date: string, anchorId: string, newPosition: number) {
    const dayPlan = plans.value[date] ?? (date === activeDate.value ? plan.value : null)
    if (!dayPlan?.anchors[anchorId]) return
    const tasks = dayPlan.anchors[anchorId].tasks
    const idx = tasks.findIndex(t => t.id === taskUuid)
    if (idx === -1) return
    const [task] = tasks.splice(idx, 1)
    tasks.splice(newPosition, 0, task)
    tasks.forEach((t, i) => { t.position = i })
    await api(`/api/tasks/${taskUuid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ position: newPosition }),
    })
  }

  async function updateAnchorTasks(anchorId: string, tasks: Task[], notes: string) {
    if (!plan.value) return
    const anchor = plan.value.anchors[anchorId]
    if (!anchor) {
      plan.value.anchors[anchorId] = { tasks, notes }
    } else {
      // Mutate in-place to keep the array reference stable for the drag directive
      anchor.tasks.splice(0, anchor.tasks.length, ...tasks)
      anchor.notes = notes
    }
    const resp = await api(`/api/plan/${activeDate.value}/anchors/${anchorId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tasks, notes }),
    })
    const data = await resp.json()
    if (data.tasks && plan.value.anchors[anchorId]) {
      // Mutate in-place to sync server-assigned UUIDs without breaking the reference
      const arr = plan.value.anchors[anchorId].tasks
      arr.splice(0, arr.length, ...data.tasks)
    }
  }

  async function updateTaskStatus(taskId: string, status: TaskStatus) {
    await api(`/api/tasks/${taskId}`, {
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
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws`)
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'plan_updated') fetchPlan()
    }
    ws.onclose = () => setTimeout(connectWebSocket, 3000)
    return ws
  }

  return {
    plan, loading, today, activeDate, savedDates, plans,
    fetchPlan, fetchSavedDates,
    goToPrevDay, goToNextDay, goToToday,
    fetchPlanRange, moveTask, reorderTask,
    updateAnchorTasks, updateTaskStatus, connectWebSocket,
  }
})
