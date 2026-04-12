<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { Milestone } from '../stores/milestones'

const props = defineProps<{
  anchorId: string
  anchorName: string
  time: string
  color: string
  date?: string
}>()

const store = usePlanStore()
const ulRef = ref<HTMLElement | null>(null)
const dragOver = ref(false)
const effectiveDate = computed(() => props.date ?? store.activeDate)
const dayPlan = computed(() => props.date ? store.plans[props.date] : store.plan)
const anchorPlan = computed(() => dayPlan.value?.anchors[props.anchorId] ?? { tasks: [], notes: '' })

const milestoneStore = useMilestoneStore()

const groupedTasks = computed(() => {
  const byMilestone: Record<string, { milestone: Milestone; tasks: { task: Task; index: number }[] }> = {}
  const ungrouped: { task: Task; index: number }[] = []

  anchorPlan.value.tasks.forEach((task, index) => {
    const milestones = milestoneStore.taskMilestones[task.id]
    if (milestones?.length) {
      const m = milestones[0]
      if (!byMilestone[m.id]) byMilestone[m.id] = { milestone: m, tasks: [] }
      byMilestone[m.id].tasks.push({ task, index })
    } else {
      ungrouped.push({ task, index })
    }
  })

  return { milestoneGroups: Object.values(byMilestone), ungrouped }
})

function onUpdate(task: Task, index: number) {
  const updated = [...anchorPlan.value.tasks]
  updated[index] = task
  store.updateAnchorTasks(props.anchorId, updated, anchorPlan.value.notes ?? '')
}

async function onRemove(index: number) {
  const task = anchorPlan.value.tasks[index]
  if (task?.id) {
    await fetch(`/api/tasks/${task.id}`, { method: 'DELETE', credentials: 'include' })
  }
  const updated = anchorPlan.value.tasks.filter((_, i) => i !== index)
  store.updateAnchorTasks(props.anchorId, updated, anchorPlan.value.notes ?? '')
}

function onAddNewTask() {
  const effectivePlan = props.date ? store.plans[props.date] : store.plan
  if (!effectivePlan) return
  if (!effectivePlan.anchors[props.anchorId]) {
    effectivePlan.anchors[props.anchorId] = { tasks: [], notes: '' }
  }
  const tasks = effectivePlan.anchors[props.anchorId].tasks
  tasks.push({
    id: '', text: '', description: null, status: 'pending' as const,
    position: tasks.length, followup_config: null, blocks: [], blocked_by: [],
    context_subject: null,
  })
  nextTick(() => {
    const inputs = ulRef.value?.querySelectorAll('input')
    if (inputs?.length) (inputs[inputs.length - 1] as HTMLInputElement).focus()
  })
}

// ── Drag and drop (native HTML5 DnD) ─────────────────────────────────────────
// The wrapper <div> is NOT draggable by default so inputs/buttons work normally.
// Pressing the handle dynamically enables draggable on the wrapper, making the
// entire row the drag ghost. Releasing the mouse removes draggable.

let activeDragEl: HTMLElement | null = null

function onHandleMouseDown(evt: MouseEvent) {
  const row = (evt.currentTarget as HTMLElement).parentElement
  if (!row) return
  row.setAttribute('draggable', 'true')
  activeDragEl = row
  document.addEventListener('mouseup', clearDraggable, { once: true })
}

function clearDraggable() {
  if (activeDragEl) {
    activeDragEl.removeAttribute('draggable')
    activeDragEl = null
  }
}

function onDragStart(evt: DragEvent, task: Task) {
  if (!task.id) { evt.preventDefault(); return }
  evt.dataTransfer!.effectAllowed = 'move'
  evt.dataTransfer!.setData('text/plain', JSON.stringify({
    taskId: task.id,
    fromAnchorId: props.anchorId,
    fromDate: effectiveDate.value,
  }))
}

function onDragEnd() {
  clearDraggable()
}

function onDragOver() {
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

function onDrop(evt: DragEvent, toIndex: number) {
  dragOver.value = false
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const { taskId, fromAnchorId, fromDate } = JSON.parse(raw)
    if (!taskId) return
    if (fromAnchorId === props.anchorId && fromDate === effectiveDate.value) {
      store.reorderTask(taskId, effectiveDate.value, props.anchorId, toIndex)
    } else {
      store.moveTask(taskId, fromDate, fromAnchorId, effectiveDate.value, props.anchorId, toIndex)
    }
  } catch { /* ignore malformed data from other drag sources */ }
}
</script>

<template>
  <GroupContainer :label="`${anchorName} · ${time}`" :color="color" :collapsible="true" :level="0">
    <template #header-right>
      <span class="text-xs text-white/30">{{ anchorPlan.tasks.length }}</span>
    </template>

    <!-- Milestone groups -->
    <GroupContainer
      v-for="group in groupedTasks.milestoneGroups"
      :key="group.milestone.id"
      :label="group.milestone.name"
      :color="group.milestone.color ?? undefined"
      :level="1"
      class="mb-2">
      <div
        v-for="{ task, index: i } in group.tasks"
        :key="task.id || i"
        :data-task-id="task.id"
        class="group flex items-center"
        @dragstart="onDragStart($event, task)"
        @dragend="onDragEnd"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.stop.prevent="onDrop($event, i)">
        <span
          class="cursor-grab text-white/30 hover:text-white/60 select-none px-1 flex-shrink-0 leading-none"
          @mousedown="onHandleMouseDown">⠿</span>
        <TaskCard
          class="flex-1 min-w-0"
          :task="task"
          @update="onUpdate($event, i)"
          @remove="onRemove(i)" />
      </div>
    </GroupContainer>

    <!-- Ungrouped tasks -->
    <ul
      ref="ulRef"
      class="space-y-1 min-h-[2rem] rounded transition-colors"
      :class="dragOver ? 'bg-white/10 ring-2 ring-white/30' : ''"
      @dragover.prevent="onDragOver"
      @dragleave="onDragLeave"
      @drop.prevent="onDrop($event, anchorPlan.tasks.length)">
      <div
        v-for="{ task, index: i } in groupedTasks.ungrouped"
        :key="task.id || i"
        :data-task-id="task.id"
        class="group flex items-center"
        @dragstart="onDragStart($event, task)"
        @dragend="onDragEnd"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.stop.prevent="onDrop($event, i)">
        <span
          class="cursor-grab text-white/30 hover:text-white/60 select-none px-1 flex-shrink-0 leading-none"
          @mousedown="onHandleMouseDown">⠿</span>
        <TaskCard
          class="flex-1 min-w-0"
          :task="task"
          @update="onUpdate($event, i)"
          @remove="onRemove(i)" />
      </div>
    </ul>

    <button type="button" @click="onAddNewTask"
            class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
  </GroupContainer>
</template>
