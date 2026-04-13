<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import KanbanColumn from '../components/KanbanColumn.vue'
import { useKanbanStore } from '../stores/kanban'
import { useMilestoneStore } from '../stores/milestones'
import type { Task, TaskStatus } from '../stores/plan'
import { api } from '../lib/api'

interface KanbanTask extends Task {
  plan_date: string | null
  anchor_id: string | null
}

const router = useRouter()
const kanbanStore = useKanbanStore()
const milestoneStore = useMilestoneStore()

const allTasks = ref<KanbanTask[]>([])
const tasksLoading = ref(false)

async function fetchAllTasks() {
  tasksLoading.value = true
  try {
    const resp = await api('/api/tasks/all')
    if (!resp.ok) throw new Error(`${resp.status}`)
    allTasks.value = await resp.json()
  } catch (e) {
    console.error('fetchAllTasks error:', e)
  } finally {
    tasksLoading.value = false
  }
}

onMounted(() => {
  kanbanStore.fetchColumns()
  milestoneStore.fetchAll()
  fetchAllTasks()
})

async function onAddTask() {
  try {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'New task' }),
    })
    if (!resp.ok) throw new Error(`${resp.status}`)
    const task = await resp.json()
    await fetchAllTasks() // refresh
    router.push({ name: 'kanban-task', params: { taskId: task.id } })
  } catch (e) {
    console.error('Failed to create task:', e)
  }
}

const VALID_STATUSES: Set<string> = new Set(['pending', 'in_progress', 'done', 'skipped', 'blocked'])
const pendingDrops = new Set<string>()

async function onTaskDrop(taskId: string, columnId: string) {
  if (pendingDrops.has(taskId)) return // ignore while a drop is in-flight for this task

  const column = kanbanStore.columns.find(c => c.id === columnId)
  if (!column) return

  const task = allTasks.value.find(t => t.id === taskId)
  if (!task) return

  const rules = column.entry_rules
  const setStatus = rules['set_status']
  if (typeof setStatus !== 'string') return
  if (!VALID_STATUSES.has(setStatus)) return

  // Build the patch — status change + optional plan_date for scheduling
  const patch: Record<string, unknown> = {}
  if (task.status !== setStatus) patch.status = setStatus
  if (rules['prompt_schedule'] && !task.plan_date) {
    patch.plan_date = new Date().toISOString().slice(0, 10) // default to today
  }

  if (!Object.keys(patch).length) return

  // Optimistic update
  const oldStatus = task.status
  const oldPlanDate = task.plan_date
  if (patch.status) task.status = patch.status as TaskStatus
  if (patch.plan_date) task.plan_date = patch.plan_date as string
  pendingDrops.add(taskId)

  try {
    const resp = await api(`/api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!resp.ok) throw new Error(`PATCH failed: ${resp.status}`)
  } catch (e) {
    console.error('Failed to update task:', e)
    task.status = oldStatus
    task.plan_date = oldPlanDate
    await fetchAllTasks()
  } finally {
    pendingDrops.delete(taskId)
  }
}

/** For each column, evaluate match rules against all tasks. First matching column wins. */
const columnTasks = computed(() => {
  const cols = kanbanStore.columns
  const result: Record<string, KanbanTask[]> = {}
  for (const col of cols) {
    result[col.id] = []
  }

  for (const task of allTasks.value) {
    for (const col of cols) {
      if (matchesRules(task, col.match_rules)) {
        result[col.id].push(task)
        break
      }
    }
  }

  return result
})

const KNOWN_RULE_KEYS = new Set(['status', 'plan_date'])

function matchesRules(task: KanbanTask, rules: Record<string, unknown>): boolean {
  for (const [key, value] of Object.entries(rules)) {
    if (!KNOWN_RULE_KEYS.has(key)) return false
    if (key === 'status') {
      if (task.status !== value) return false
    } else if (key === 'plan_date') {
      if (value === null) {
        if (task.plan_date !== null) return false
      } else if (value === 'not_null') {
        if (task.plan_date === null) return false
      } else {
        return false
      }
    }
  }
  return true
}
</script>

<template>
  <div class="h-screen bg-gray-900 text-white p-6 flex flex-col overflow-hidden">
    <h1 class="text-2xl font-bold mb-4 flex-shrink-0">Kanban</h1>

    <div v-if="kanbanStore.loading || tasksLoading" class="text-white/40 text-sm">Loading...</div>
    <div v-else-if="kanbanStore.error" class="text-red-400 text-sm">{{ kanbanStore.error }}</div>

    <div v-else class="flex gap-4 overflow-x-auto flex-1 min-h-0">
      <KanbanColumn
        v-for="col in kanbanStore.columns"
        :key="col.id"
        :column="col"
        :tasks="columnTasks[col.id] ?? []"
        @add-task="onAddTask"
        @task-drop="onTaskDrop" />
    </div>

    <router-view />
  </div>
</template>
