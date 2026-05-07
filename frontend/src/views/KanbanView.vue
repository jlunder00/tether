<script setup lang="ts">
import { onMounted, computed } from 'vue'
import KanbanColumn from '../components/KanbanColumn.vue'
import { useKanbanStore, type KanbanTask } from '../stores/kanban'
import { useMilestoneStore } from '../stores/milestones'
import { api } from '../lib/api'
import { useSlideOver } from '../composables/useSlideOver'

const { push: pushPanel } = useSlideOver()
const kanbanStore = useKanbanStore()
const milestoneStore = useMilestoneStore()

onMounted(() => {
  kanbanStore.fetchColumns()
  milestoneStore.fetchAll()
  kanbanStore.fetchAllTasks()
})

async function onAddTask(columnId: string, opts: { context_subject?: string; milestone_id?: string }) {
  const col = kanbanStore.columns.find(c => c.id === columnId)
  if (!col) return
  const body: Record<string, unknown> = { text: 'New task', ...opts }
  const rules = col.entry_rules ?? {}
  if (typeof rules['set_status'] === 'string') body.status = rules['set_status']
  if (rules['prompt_schedule']) {
    body.date = new Date().toISOString().slice(0, 10)
  }
  try {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(`${resp.status}`)
    const task = await resp.json()
    await kanbanStore.fetchAllTasks()
    pushPanel({ kind: 'task', entityId: task.id })
  } catch (e) {
    console.error('Failed to create task:', e)
  }
}

async function onTaskDrop(taskId: string, columnId: string) {
  await kanbanStore.moveTaskToColumn(taskId, columnId)
}

/** For each column, evaluate match rules against all tasks. First matching column wins. */
const columnTasks = computed(() => {
  const cols = kanbanStore.columns
  const result: Record<string, KanbanTask[]> = {}
  for (const col of cols) {
    result[col.id] = []
  }

  for (const task of kanbanStore.allTasks) {
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
  <div class="h-screen bg-[--bg-canvas] text-[--fg-1] p-6 flex flex-col overflow-hidden">
    <h1 class="text-2xl font-bold mb-4 flex-shrink-0">Kanban</h1>

    <div v-if="kanbanStore.loading || kanbanStore.tasksLoading" class="text-[--fg-4] text-sm">Loading...</div>
    <div v-else-if="kanbanStore.error" class="text-[--status-block-fg] text-sm">{{ kanbanStore.error }}</div>

    <div v-else class="flex gap-4 overflow-x-auto flex-1 min-h-0">
      <KanbanColumn
        v-for="col in kanbanStore.columns"
        :key="col.id"
        :column="col"
        :tasks="columnTasks[col.id] ?? []"
        @add-task="(opts) => onAddTask(col.id, opts)"
        @task-drop="onTaskDrop" />
    </div>
  </div>
</template>
