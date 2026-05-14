import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { FollowupConfig } from './anchors'
import { api } from '../lib/api'
import { localDateString } from '../lib/dateUtils'

export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'skipped' | 'blocked'

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
  // Plan date — present on backlog/kanban tasks (null when unscheduled)
  plan_date?: string | null
  // Recurrence fields — anchor-recurring tasks only
  rrule?: string | null
  is_recurring_master?: boolean
  original_date?: string
  color?: string | null
  motif?: string | null
}

export interface AnchorPlan { tasks: Task[]; notes: string }
export interface DayPlan {
  date: string
  anchors: Record<string, AnchorPlan>
  acknowledgements: Record<string, string>
  check_in_log: unknown[]
}

export const usePlanStore = defineStore('plan', () => {
  const plan = ref<DayPlan | null>(null)
  const loading = ref(false)
  const today = localDateString(new Date())
  const activeDate = ref(today)
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

  // Deprecated: superceeded by routing via router.push()

  async function fetchPlanRange(startDate: string, endDate: string) {
    const resp = await api(`/api/plan/range?start=${startDate}&end=${endDate}`)
    const data: Record<string, DayPlan> = await resp.json()
    plans.value = { ...plans.value, ...data }
    // Sym 1 fix: keep plan.value (single-day cache) in sync so AnchorBlocks in PlanView
    // (which read store.plan, not store.plans[date]) reflect promotions and demotions
    // without requiring a fetchPlan call that would flip loading and destroy the grid.
    if (data[activeDate.value]) {
      plan.value = data[activeDate.value]
    }
  }

  async function moveTask(
    taskUuid: string,
    fromDate: string, fromAnchor: string,
    toDate: string, toAnchor: string,
    position?: number,
  ) {
    // Sym 3 fix: update ALL caches that contain the affected date so that both
    // AnchorBlocks in PlanView (reading plan.value) and CalendarView (reading
    // plans.value[date]) see the change immediately.
    // Build the candidate source/target objects for each cache layer.
    const fromCandidates: (DayPlan | null)[] = [
      plans.value[fromDate] ?? null,
      fromDate === activeDate.value ? plan.value : null,
    ]
    const toCandidates: (DayPlan | null)[] = [
      plans.value[toDate] ?? null,
      toDate === activeDate.value ? plan.value : null,
    ]

    // Deduplicate: when plans.value[date] and plan.value point to different objects,
    // we want to mutate both. When they're the same object (shouldn't happen normally),
    // the second mutation is a no-op because the task was already removed/inserted.
    const seen = new Set<DayPlan>()
    let task: Task | undefined

    // Find the task in any from-candidate (use first match)
    for (const fromDay of fromCandidates) {
      if (!fromDay || seen.has(fromDay)) continue
      seen.add(fromDay)
      const found = fromDay.anchors[fromAnchor]?.tasks.find(t => t.id === taskUuid)
      if (found && !task) task = found as any
      if (found) {
        fromDay.anchors[fromAnchor].tasks = fromDay.anchors[fromAnchor].tasks.filter(t => t.id !== taskUuid)
      }
    }

    // Insert into all to-candidates that are populated
    const toSeen = new Set<DayPlan>()
    if (task) {
      for (const toDay of toCandidates) {
        if (!toDay || toSeen.has(toDay)) continue
        toSeen.add(toDay)
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

  /**
   * Move a task to a new date/anchor cell. PATCHes both plan_date and anchor_id
   * atomically (Track B confirmed both fields are accepted). Optimistically
   * removes the task from its source cell (scans all cached plans + the active
   * plan) and inserts it into the target cell if that day is already cached.
   */
  async function moveTaskToAnchor({
    taskId,
    newDate,
    anchorId,
  }: { taskId: string; newDate: string; anchorId: string }) {
    // --- Optimistic update ---
    // Find task in any cached plan and remove it from its source anchor.
    let foundTask: Task | undefined

    // Search plans range cache first
    for (const dayPlan of Object.values(plans.value)) {
      for (const anchorPlan of Object.values(dayPlan.anchors)) {
        const idx = anchorPlan.tasks.findIndex(t => t.id === taskId)
        if (idx !== -1) {
          foundTask = anchorPlan.tasks[idx]
          anchorPlan.tasks.splice(idx, 1)
          break
        }
      }
      if (foundTask) break
    }

    // Fall back to the active single-day plan
    if (!foundTask && plan.value) {
      for (const anchorPlan of Object.values(plan.value.anchors)) {
        const idx = anchorPlan.tasks.findIndex(t => t.id === taskId)
        if (idx !== -1) {
          foundTask = anchorPlan.tasks[idx]
          anchorPlan.tasks.splice(idx, 1)
          break
        }
      }
    }

    // Insert into target cell if that day is already in the range cache
    if (foundTask) {
      const targetDay = plans.value[newDate]
      if (targetDay) {
        if (!targetDay.anchors[anchorId]) {
          targetDay.anchors[anchorId] = { tasks: [], notes: '' }
        }
        // Include updated anchor_id so the task reflects its new home in cache
        targetDay.anchors[anchorId].tasks.push({ ...foundTask, anchor_id: anchorId })
      }
    }

    // --- API call (plan_date + anchor_id — Track B confirmed both fields work) ---
    await api(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plan_date: newDate, anchor_id: anchorId }),
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

  /**
   * PATCH arbitrary fields on a task. Applies optimistic update to the in-memory
   * plan so the UI reflects the change immediately. Returns true on success.
   *
   * Components must route all task PATCHes through this action — never call
   * api() directly from component script (standing rule).
   */
  async function patchTaskFields(taskId: string, fields: Record<string, unknown>): Promise<boolean> {
    const resp = await api(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    if (resp.ok) {
      // Update task in single-day plan (plan view)
      if (plan.value?.anchors) {
        for (const anchor of Object.values(plan.value.anchors)) {
          const task = anchor.tasks.find(t => t.id === taskId)
          if (task) { Object.assign(task, fields); break }
        }
      }
      // Update task in range cache (CalendarView uses plans for multi-day display)
      for (const dayPlan of Object.values(plans.value)) {
        if (!dayPlan?.anchors) continue
        for (const anchor of Object.values(dayPlan.anchors)) {
          const task = anchor.tasks.find(t => t.id === taskId)
          if (task) { Object.assign(task, fields); break }
        }
      }
    }
    return resp.ok
  }

  /**
   * Move a backlog task onto a specific date+anchor (schedule it).
   * Calls PUT /api/tasks/:id/move.
   */
  async function scheduleTask(taskId: string, date: string, anchorId: string): Promise<void> {
    await api(`/api/tasks/${taskId}/move`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, anchor_id: anchorId }),
    })
  }

  /**
   * Optimistically insert a stub task into both plan caches immediately.
   * Call this before awaiting the PATCH in eventStore.demoteEvent so the task
   * appears in the anchor the moment the calendar event disappears — before
   * the round-trip completes. The stub is keyed by its real task id, so the
   * subsequent fetchPlanRange reconciles by id when the server response arrives.
   *
   * Uses the same dual-cache pattern as moveTask: writes to both plan.value
   * (single-day cache read by AnchorBlocks in PlanView) and plans.value[date]
   * (range cache read by CalendarView). A `seen` set prevents a double-insert
   * when the two references point to the same object (fetchPlanRange aliases them).
   *
   * If neither cache contains the target date, this is a no-op — the task will
   * appear after the next fetchPlanRange.
   */
  function insertStubTask(date: string, anchorId: string, task: Task): void {
    const candidates: (DayPlan | null)[] = [
      plans.value[date] ?? null,
      date === activeDate.value ? plan.value : null,
    ]
    const seen = new Set<DayPlan>()
    for (const dayPlan of candidates) {
      if (!dayPlan || seen.has(dayPlan)) continue
      seen.add(dayPlan)
      if (!dayPlan.anchors[anchorId]) {
        dayPlan.anchors[anchorId] = { tasks: [], notes: '' }
      }
      // Idempotent: skip if a task with this id is already present
      if (!dayPlan.anchors[anchorId].tasks.find(t => t.id === task.id)) {
        dayPlan.anchors[anchorId].tasks.push(task)
      }
    }
  }

  /**
   * Optimistically remove a task from ALL plan caches by id.
   * Call this immediately after eventStore.promoteTask to hide the source task
   * from AnchorBlocks without a network round-trip. The event store's promoteTask
   * has already added the new event to events.value, so the calendar side updates
   * immediately — this makes the plan-sidebar side equally instant.
   *
   * Sym 4 fix: replaces the full-week fetchPlanRange call in CalendarView's
   * drop handler, eliminating the network-induced lag between drop and source hide.
   *
   * Also used by demoteEvent error path to roll back a stub task inserted by
   * insertStubTask when the PATCH request fails.
   */
  function removeTaskFromPlans(taskId: string): void {
    // Remove from range cache (all cached days)
    for (const dayPlan of Object.values(plans.value)) {
      if (!dayPlan?.anchors) continue
      for (const anchor of Object.values(dayPlan.anchors)) {
        const idx = anchor.tasks.findIndex(t => t.id === taskId)
        if (idx !== -1) { anchor.tasks.splice(idx, 1); break }
      }
    }
    // Remove from single-day plan (PlanView's AnchorBlocks read this)
    if (plan.value?.anchors) {
      for (const anchor of Object.values(plan.value.anchors)) {
        const idx = anchor.tasks.findIndex(t => t.id === taskId)
        if (idx !== -1) { anchor.tasks.splice(idx, 1); break }
      }
    }
  }

  /**
   * Unschedule a plan task — move it back to the backlog (date: null, anchor_id: null).
   */
  async function moveToBacklog(taskId: string): Promise<void> {
    await api(`/api/tasks/${taskId}/move`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date: null, anchor_id: null }),
    })
  }

  /**
   * Create a new task directly on a specific date+anchor.
   * Used by AnchorBlock.onAddNewTask and DashboardView.onAddTaskToNow.
   */
  async function createPlanTask(
    date: string,
    anchorId: string,
    opts: { text?: string; context_subject?: string; milestone_id?: string } = {},
  ): Promise<Task | null> {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: opts.text ?? 'New task', date, anchor_id: anchorId, ...opts }),
    })
    if (!resp.ok) return null
    return resp.json()
  }

  // Deprecated: superceeded by auth store manage ws transport in /api/bot/chat

  return {
    plan, loading, today, activeDate, plans,
    fetchPlan,
    fetchPlanRange, moveTask, moveTaskToAnchor, reorderTask,
    updateAnchorTasks, updateTaskStatus, patchTaskFields,
    scheduleTask, moveToBacklog, createPlanTask,
    insertStubTask, removeTaskFromPlans,
  }
})
