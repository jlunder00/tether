<script setup lang="ts">
import type { Task, TaskStatus } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
const milestoneStore = useMilestoneStore()

const props = defineProps<{ task: Task }>()
const emit = defineEmits<{
  (e: 'update', task: Task): void
  (e: 'remove'): void
}>()

const STATUS_CYCLE: TaskStatus[] = ['pending', 'in_progress', 'done']
const STATUS_COLORS: Record<TaskStatus, string> = {
  pending:     'bg-white/20 hover:bg-white/40',
  in_progress: 'bg-blue-400 hover:bg-blue-300',
  done:        'bg-green-400 hover:bg-green-300',
  skipped:     'bg-orange-400 hover:bg-orange-300',
  blocked:     'bg-red-400 hover:bg-red-300',
}

function cycleStatus() {
  const idx = STATUS_CYCLE.indexOf(props.task.status)
  const next = STATUS_CYCLE[idx === -1 ? 0 : (idx + 1) % STATUS_CYCLE.length]
  emit('update', { ...props.task, status: next })
}

function updateText(e: Event) {
  emit('update', { ...props.task, text: (e.target as HTMLInputElement).value })
}
</script>

<template>
  <li class="flex gap-2 items-center group">
    <span class="drag-handle cursor-grab text-white/25 select-none opacity-0 group-hover:opacity-100 transition-opacity leading-none">⠿</span>
    <button
      @click="cycleStatus"
      :class="STATUS_COLORS[task.status]"
      :title="task.status"
      class="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5 transition-colors cursor-pointer" />
    <input
      :value="task.text"
      :class="task.status === 'done' ? 'line-through opacity-40' : ''"
      @change="updateText"
      class="flex-1 bg-transparent border-b border-white/20 focus:border-white/60 outline-none text-sm py-0.5" />
    <span
      v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
      class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/50 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
      {{ m.name }}
    </span>
    <button
      @click="emit('remove')"
      class="text-white/30 hover:text-white/70 text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
  </li>
</template>
