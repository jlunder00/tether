<script setup lang="ts">
import { ref, onMounted } from 'vue'
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

async function addTask() {
  const text = newTaskText.value.trim()
  if (!text) return
  const task = await backlogStore.createTask(text)
  newTaskText.value = ''
  // Open detail panel for the new task so user can add description/subtasks
  router.push(`/backlog/task/${task.id}`)
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h1 class="text-2xl font-bold mb-2">Backlog</h1>
    <p class="text-white/40 text-sm mb-6">Unscheduled tasks — add details, then let the bot schedule them.</p>

    <div class="max-w-2xl">
      <!-- Add task -->
      <div class="flex gap-2 mb-4">
        <input
          v-model="newTaskText"
          @keydown.enter="addTask"
          placeholder="+ Add task to backlog..."
          class="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm outline-none focus:border-white/30" />
        <button @click="addTask"
                class="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-lg text-sm transition-colors">Add</button>
      </div>

      <!-- Task list -->
      <div v-if="backlogStore.loading" class="text-white/40 text-sm">Loading...</div>
      <ul v-else class="flex flex-col gap-1.5">
        <li v-for="task in backlogStore.tasks" :key="task.id"
            class="flex items-center gap-3 bg-white/5 rounded-lg px-3 py-2 hover:bg-white/10 cursor-pointer transition-colors group"
            @click="router.push(`/backlog/task/${task.id}`)">
          <span class="w-2 h-2 rounded-full flex-shrink-0"
                :class="task.status === 'done' ? 'bg-green-400' : task.status === 'in_progress' ? 'bg-blue-400' : 'bg-white/20'" />
          <span class="flex-1 text-sm" :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
          <span v-if="task.description" class="text-white/20 text-xs">has description</span>
          <span class="text-white/20 text-xs opacity-0 group-hover:opacity-100 transition-opacity">↗</span>
        </li>
      </ul>
      <p v-if="!backlogStore.loading && !backlogStore.tasks.length"
         class="text-white/20 text-sm mt-4">No unscheduled tasks. Add one above, or use MCP tools to create tasks.</p>
    </div>

    <router-view />
  </div>
</template>
