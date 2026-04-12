<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBacklogStore } from '../stores/backlog'
import { useMilestoneStore } from '../stores/milestones'
import type { Milestone } from '../stores/milestones'
import type { Task } from '../stores/plan'
import TaskCard from '../components/TaskCard.vue'
import GroupContainer from '../components/GroupContainer.vue'

const router = useRouter()
const backlogStore = useBacklogStore()
const milestoneStore = useMilestoneStore()
const newTaskText = ref('')

onMounted(() => {
  backlogStore.fetchTasks()
  milestoneStore.fetchAll()
})

// Group tasks by first context subject (or "Uncategorized")
const grouped = computed(() => {
  const groups: Record<string, typeof backlogStore.tasks> = {}
  for (const task of backlogStore.tasks) {
    const ctx = task.context_subject ?? 'Uncategorized'
    if (!groups[ctx]) groups[ctx] = []
    groups[ctx].push(task)
  }
  // Sort: Uncategorized last
  const sorted = Object.entries(groups).sort(([a], [b]) => {
    if (a === 'Uncategorized') return 1
    if (b === 'Uncategorized') return -1
    return a.localeCompare(b)
  })
  return sorted
})

function tasksByMilestone(tasks: Task[]) {
  const byMs = new Map<string, { milestone: Milestone; tasks: Task[] }>()
  const noMs: Task[] = []
  for (const t of tasks) {
    const ms = milestoneStore.taskMilestones[t.id]
    if (!ms?.length) { noMs.push(t); continue }
    const m = ms[0]
    if (!byMs.has(m.id)) byMs.set(m.id, { milestone: m, tasks: [] })
    byMs.get(m.id)!.tasks.push(t)
  }
  return { milestoneGroups: [...byMs.values()], ungrouped: noMs }
}

async function addTask() {
  const text = newTaskText.value.trim()
  if (!text) return
  const task = await backlogStore.createTask(text)
  newTaskText.value = ''
  router.push(`/backlog/task/${task.id}`)
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h1 class="text-2xl font-bold mb-2">Backlog</h1>
    <p class="text-white/40 text-sm mb-6">Unscheduled tasks — add details, then let the bot schedule them.</p>

    <div class="max-w-2xl">
      <!-- Add task -->
      <div class="flex gap-2 mb-6">
        <input
          v-model="newTaskText"
          @keydown.enter="addTask"
          placeholder="+ Add task to backlog..."
          class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30" />
        <button @click="addTask"
                class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition-colors">Add</button>
      </div>

      <!-- Loading -->
      <div v-if="backlogStore.loading" class="text-white/40 text-sm">Loading...</div>

      <!-- Grouped task list -->
      <template v-else-if="grouped.length">
        <div v-for="[context, tasks] in grouped" :key="context" class="mb-5">
          <GroupContainer :label="context" :level="0">
            <template v-for="mg in tasksByMilestone(tasks).milestoneGroups" :key="mg.milestone.id">
              <GroupContainer :label="mg.milestone.name" :color="mg.milestone.color ?? undefined" :level="1">
                <ul class="flex flex-col gap-1.5">
                  <TaskCard v-for="task in mg.tasks" :key="task.id"
                    :task="task" :editable="false" :show-remove="false" :show-detail-link="false" :compact="true" :hide-tags="true" />
                </ul>
              </GroupContainer>
            </template>
            <ul v-if="tasksByMilestone(tasks).ungrouped.length" class="flex flex-col gap-1.5">
              <TaskCard v-for="task in tasksByMilestone(tasks).ungrouped" :key="task.id"
                :task="task" :editable="false" :show-remove="false" :show-detail-link="false" :compact="true" :hide-tags="true" />
            </ul>
          </GroupContainer>
        </div>
      </template>

      <p v-else class="text-white/20 text-sm mt-4">No unscheduled tasks. Add one above, or use MCP tools to create tasks.</p>
    </div>

    <router-view />
  </div>
</template>
