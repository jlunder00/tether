<script setup lang="ts">
import { ref } from 'vue'
import { usePlanStore } from '../../stores/plan'
import type { Task } from '../../stores/plan'
import TaskCard from '../TaskCard.vue'

const props = defineProps<{
  date: string
  anchorId: string
  anchorName: string
  tasks: Task[]
}>()

const planStore = usePlanStore()

// ── Drag-over visual state ────────────────────────────────────────────────────
const isDragOver = ref(false)

function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

// ── Drop: move task to this anchor×day cell ───────────────────────────────────
async function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false

  const raw = e.dataTransfer?.getData('text/plain')
  if (!raw) return

  let payload: { taskId?: string }
  try {
    payload = JSON.parse(raw)
  } catch {
    return // ignore malformed drag data from other drag sources
  }

  if (!payload.taskId) return

  await planStore.moveTaskToAnchor({
    taskId: payload.taskId,
    newDate: props.date,
    anchorId: props.anchorId,
  })
}
</script>

<template>
  <div
    data-testid="week-cell-drop"
    class="min-h-[80px] p-1 rounded transition-colors"
    :class="[
      isDragOver
        ? 'ring-1 ring-[--accent] bg-[--accent-veil]'
        : 'bg-[--bg-elev-1] hover:bg-[--bg-elev-2]',
    ]"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <div class="flex flex-col gap-0.5">
      <TaskCard
        v-for="task in tasks"
        :key="task.id"
        :task="task"
        :hide-tags="true"
        class="text-xs"
      />
      <div v-if="!tasks.length" class="text-[11px] text-[--fg-6] px-1 py-0.5 italic">
        No tasks
      </div>
    </div>
  </div>
</template>
