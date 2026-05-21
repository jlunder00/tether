<script setup lang="ts">
import { toRef, computed } from 'vue'
import { useDraggableTask } from '../composables/useDraggableTask'
import type { Task } from '../stores/plan'

/**
 * A single sidebar task item in CalendarView's anchor panel.
 *
 * Encapsulates the drag-source logic via useDraggableTask so that:
 *   1. isDragging is per-instance (one composable per task, not a shared draggingTaskId ref)
 *   2. The rAF-deferred source-hiding and dataTransfer payload are handled by the composable
 *   3. CalendarView's inline dragstart handler + draggingTaskId ref can be removed
 *
 * This migration makes CalendarView's sidebar consistent with useDraggableTask —
 * the same pattern used by AnchorBlock (which also uses its own inline ref, but this
 * component provides the composable-based path for new consumers).
 */
const props = defineProps<{
  task: Task
  anchorId: string
  fromDate: string
}>()

const emit = defineEmits<{
  click: [taskId: string]
}>()

// toRef keeps the task reactive when the parent's v-for list updates
const taskRef = toRef(props, 'task')
const contextRef = computed(() => ({
  fromAnchorId: props.anchorId,
  fromDate: props.fromDate,
}))

const { isDragging, dragHandlers } = useDraggableTask(taskRef, contextRef)
</script>

<template>
  <li
    v-show="!isDragging"
    draggable="true"
    class="text-xs px-1.5 py-1 rounded cursor-grab hover:bg-[--bg-elev-2] text-[--fg-3] hover:text-[--fg-1] transition-colors truncate"
    :class="task.status === 'done' ? 'line-through opacity-40' : ''"
    @click.stop="emit('click', task.id)"
    @dragstart="dragHandlers.onDragStart"
    @dragend="dragHandlers.onDragEnd"
  >{{ task.text }}</li>
</template>
