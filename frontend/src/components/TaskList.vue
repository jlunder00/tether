<script setup lang="ts">
import type { Task } from '../stores/plan'
import TaskCard from './TaskCard.vue'

const props = defineProps<{ tasks: Task[] }>()
const emit = defineEmits<{ (e: 'update', tasks: Task[]): void }>()

function updateTask(index: number, task: Task) {
  const t = [...props.tasks]; t[index] = task; emit('update', t)
}
function add() {
  emit('update', [
    ...props.tasks,
    { id: '', text: '', description: null, status: 'pending', position: props.tasks.length,
      followup_config: null, blocks: [], blocked_by: [], context_subject: null },
  ])
}
function remove(i: number) {
  emit('update', props.tasks.filter((_, j) => j !== i))
}
</script>

<template>
  <ul class="space-y-1">
    <TaskCard
      v-for="(task, i) in tasks"
      :key="task.id || i"
      :task="task"
      @update="updateTask(i, $event)"
      @remove="remove(i)" />
  </ul>
  <button @click="add" class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
</template>
