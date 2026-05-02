<script setup lang="ts">
import { ref } from 'vue'
import { usePlanStore } from '../../stores/plan'
import type { Task } from '../../stores/plan'
import { useDropZone } from '../../composables/useDropZone'
import TaskCard from '../TaskCard.vue'

const props = defineProps<{
  date: string
  anchorId: string
  anchorName: string
  tasks: Task[]
}>()

const planStore = usePlanStore()

// ── Source hiding ─────────────────────────────────────────────────────────────
const draggingTaskId = ref<string | null>(null)

function onTaskDragStart(evt: DragEvent, task: Task) {
  if (!task.id) { evt.preventDefault(); return }
  draggingTaskId.value = task.id
  if (!evt.dataTransfer) return
  evt.dataTransfer.effectAllowed = 'move'
  evt.dataTransfer.setData('text/plain', JSON.stringify({
    type: 'task',
    taskId: task.id,
    title: task.text,
    fromDate: props.date,
    fromAnchorId: props.anchorId,
  }))
}

function onTaskDragEnd() {
  draggingTaskId.value = null
}

// ── Drop: move task to this anchor×day cell via useDropZone ───────────────────
const { isOver, dropHandlers } = useDropZone({
  onDrop(payload) {
    const p = payload as { taskId?: string }
    if (!p.taskId) return
    planStore.moveTaskToAnchor({
      taskId: p.taskId,
      newDate: props.date,
      anchorId: props.anchorId,
    })
  },
})
</script>

<template>
  <div
    data-testid="week-cell-drop"
    class="min-h-[80px] p-1 rounded transition-colors"
    :class="[
      isOver
        ? 'ring-1 ring-[--accent] bg-[--accent-veil]'
        : 'bg-[--bg-elev-1] hover:bg-[--bg-elev-2]',
    ]"
    @dragenter="dropHandlers.onDragEnter"
    @dragover="dropHandlers.onDragOver"
    @dragleave="dropHandlers.onDragLeave"
    @drop="dropHandlers.onDrop"
  >
    <div class="flex flex-col gap-0.5">
      <div
        v-for="task in tasks"
        :key="task.id"
        :data-task-id="task.id"
        draggable="true"
        v-show="draggingTaskId !== task.id"
        @dragstart="onTaskDragStart($event, task)"
        @dragend="onTaskDragEnd"
      >
        <TaskCard
          :task="task"
          :hide-tags="true"
          class="text-xs"
        />
      </div>
      <div v-if="!tasks.length" class="text-[11px] text-[--fg-6] px-1 py-0.5 italic">
        No tasks
      </div>
    </div>
  </div>
</template>
