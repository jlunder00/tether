<script setup lang="ts">
import { useDropZone } from '../../composables/useDropZone'
import type { DropPayload } from '../../composables/useDropZone'

const props = defineProps<{
  date: string
  taskCount: number
  isToday: boolean
}>()

const emit = defineEmits<{
  (e: 'task-dropped', payload: { taskId: string; date: string; fromAnchorId?: string }): void
}>()

// Each day cell is its own drop target — calling useDropZone at setup level
// (not inside v-for) is the correct Vue 3 composable pattern.
const { isOver, dropHandlers } = useDropZone({
  onDrop(payload: DropPayload) {
    const p = payload as { taskId?: string; fromAnchorId?: string }
    if (!p.taskId) return
    emit('task-dropped', {
      taskId: p.taskId,
      date: props.date,
      fromAnchorId: p.fromAnchorId,
    })
  },
})
</script>

<template>
  <div
    :data-date="date"
    class="relative flex flex-col items-center justify-start p-0.5 rounded cursor-default min-h-[28px] transition-colors select-none"
    :class="[
      isOver ? 'ring-1 ring-[--accent] bg-[--accent-veil]' : 'hover:bg-[--bg-elev-2]',
    ]"
    @dragenter="dropHandlers.onDragEnter"
    @dragover="dropHandlers.onDragOver"
    @dragleave="dropHandlers.onDragLeave"
    @drop="dropHandlers.onDrop"
  >
    <!-- Day number -->
    <span
      class="text-[11px] font-medium leading-tight"
      :class="isToday ? 'text-[--accent] font-bold' : 'text-[--fg-3]'"
    >{{ new Date(date + 'T12:00:00').getDate() }}</span>

    <!-- Task count dot indicator -->
    <span
      v-if="taskCount > 0"
      class="text-[9px] text-[--fg-5] leading-none"
    >{{ taskCount }}</span>
  </div>
</template>
