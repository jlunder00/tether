<script setup lang="ts">
import { onMounted, computed } from 'vue'
import KanbanColumn from '../components/KanbanColumn.vue'
import { usePlanStore } from '../stores/plan'
import { useKanbanStore } from '../stores/kanban'
import { useMilestoneStore } from '../stores/milestones'
import { useBacklogStore } from '../stores/backlog'
import type { Task } from '../stores/plan'

interface KanbanTask extends Task {
  plan_date: string | null
  anchor_id: string | null
}

const planStore = usePlanStore()
const kanbanStore = useKanbanStore()
const milestoneStore = useMilestoneStore()
const backlogStore = useBacklogStore()

onMounted(() => {
  planStore.fetchPlan()
  kanbanStore.fetchColumns()
  milestoneStore.fetchAll()
  backlogStore.fetchTasks()
})

/** Combine all tasks (plan + backlog) into a single list with scheduling info */
const allTasks = computed<KanbanTask[]>(() => {
  const tasks: KanbanTask[] = []

  // Plan tasks — have plan_date and anchor_id
  if (planStore.plan) {
    for (const [anchorId, anchor] of Object.entries(planStore.plan.anchors)) {
      for (const task of anchor.tasks) {
        tasks.push({
          ...task,
          plan_date: planStore.plan.date,
          anchor_id: anchorId,
        })
      }
    }
  }

  // Backlog tasks — no schedule
  for (const task of backlogStore.tasks) {
    tasks.push({
      ...task,
      plan_date: null,
      anchor_id: null,
    })
  }

  return tasks
})

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
    if (!KNOWN_RULE_KEYS.has(key)) return false // unknown keys fail closed
    if (key === 'status') {
      if (task.status !== value) return false
    } else if (key === 'plan_date') {
      if (value === null) {
        if (task.plan_date !== null) return false
      } else if (value === 'not_null') {
        if (task.plan_date === null) return false
      }
    }
  }
  return true
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h1 class="text-2xl font-bold mb-4">Kanban</h1>

    <div v-if="kanbanStore.loading" class="text-white/40 text-sm">Loading columns...</div>

    <div v-else class="flex gap-4 overflow-x-auto pb-4" style="min-height: calc(100vh - 140px);">
      <KanbanColumn
        v-for="col in kanbanStore.columns"
        :key="col.id"
        :column="col"
        :tasks="columnTasks[col.id] ?? []" />
    </div>

    <router-view />
  </div>
</template>
