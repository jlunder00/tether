<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBacklogStore } from '../stores/backlog'
import { useMilestoneStore } from '../stores/milestones'

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
    const ctx = task.contexts?.[0] ?? 'Uncategorized'
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
          <h2 class="text-xs text-white/40 uppercase tracking-wide mb-2 flex items-center gap-2">
            <span>{{ context }}</span>
            <span class="text-white/20">{{ tasks.length }}</span>
          </h2>
          <ul class="flex flex-col gap-1.5">
            <li v-for="task in tasks" :key="task.id"
                class="flex items-center gap-3 bg-white/5 rounded-lg px-3 py-2 hover:bg-white/10 cursor-pointer transition-colors group"
                @click="router.push(`/backlog/task/${task.id}`)">
              <span class="w-2 h-2 rounded-full flex-shrink-0"
                    :class="task.status === 'done' ? 'bg-green-400' : task.status === 'in_progress' ? 'bg-blue-400' : 'bg-white/20'" />
              <span class="flex-1 text-sm" :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
              <span v-if="task.description" class="text-white/20 text-xs flex-shrink-0">has description</span>
              <span class="text-white/20 text-xs opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">↗</span>
            </li>
          </ul>
        </div>
      </template>

      <p v-else class="text-white/20 text-sm mt-4">No unscheduled tasks. Add one above, or use MCP tools to create tasks.</p>
    </div>

    <router-view />
  </div>
</template>
