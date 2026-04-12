<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import KanbanColumn from '../components/KanbanColumn.vue'
import { useKanbanStore } from '../stores/kanban'
import { useMilestoneStore } from '../stores/milestones'
import type { Task } from '../stores/plan'
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
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h1 class="text-2xl font-bold mb-4">Kanban</h1>

    <div v-if="kanbanStore.loading || tasksLoading" class="text-white/40 text-sm">Loading...</div>
    <div v-else-if="kanbanStore.error" class="text-red-400 text-sm">{{ kanbanStore.error }}</div>

    <div v-else class="flex gap-4 overflow-x-auto pb-4" style="min-height: calc(100vh - 140px);">
      <KanbanColumn
        v-for="col in kanbanStore.columns"
        :key="col.id"
        :column="col"
        :tasks="columnTasks[col.id] ?? []"
        @add-task="onAddTask" />
    </div>

    <router-view />
  </div>
</template>
