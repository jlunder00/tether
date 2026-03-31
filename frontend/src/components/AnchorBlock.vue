<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { vDraggable } from 'vue-draggable-plus'
import TaskItem from './TaskItem.vue'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'

const props = defineProps<{
  anchorId: string
  anchorName: string
  time: string
  color: string
  date?: string   // defaults to store activeDate; WeekView passes explicit date
}>()

const store = usePlanStore()
const taskContainer = ref<HTMLElement | null>(null)
const effectiveDate = computed(() => props.date ?? store.activeDate)
const dayPlan = computed(() =>
  props.date
    ? store.plans[props.date]
    : store.plan
)
const anchorPlan = computed(() => dayPlan.value?.anchors[props.anchorId] ?? { tasks: [], notes: '' })

function onUpdate(task: Task, index: number) {
  const updated = [...anchorPlan.value.tasks]
  updated[index] = task
  store.updateAnchorTasks(props.anchorId, updated, anchorPlan.value.notes ?? '')
}

function onRemove(index: number) {
  const updated = anchorPlan.value.tasks.filter((_, i) => i !== index)
  store.updateAnchorTasks(props.anchorId, updated, anchorPlan.value.notes ?? '')
}

function onAddNewTask() {
  // Push directly to reactive state — no API call yet.
  // The PUT fires when the user types text and @change triggers onUpdate.
  const effectivePlan = props.date ? store.plans[props.date] : store.plan
  if (!effectivePlan) return
  if (!effectivePlan.anchors[props.anchorId]) {
    effectivePlan.anchors[props.anchorId] = { tasks: [], notes: '' }
  }
  const tasks = effectivePlan.anchors[props.anchorId].tasks
  tasks.push({
    id: '',
    text: '',
    status: 'pending' as const,
    position: tasks.length,
    followup_config: null,
    blocks: [],
    blocked_by: [],
  })
  nextTick(() => {
    const inputs = taskContainer.value?.querySelectorAll('input')
    if (inputs?.length) (inputs[inputs.length - 1] as HTMLInputElement).focus()
  })
}

function onDragEnd(evt: any) {
  const fromAnchor = evt.from.dataset.anchorId as string
  const fromDate = evt.from.dataset.date as string
  const toAnchor = evt.to.dataset.anchorId as string
  const toDate = evt.to.dataset.date as string
  const taskId = evt.item.dataset.taskId as string
  if (!taskId) return
  if (fromAnchor === toAnchor && fromDate === toDate) {
    store.reorderTask(taskId, toDate, toAnchor, evt.newIndex)
  } else {
    store.moveTask(taskId, fromDate, fromAnchor, toDate, toAnchor, evt.newIndex)
  }
}
</script>

<template>
  <div class="flex rounded-xl overflow-hidden">
    <div class="flex flex-col justify-center px-4 py-3 min-w-[110px] text-white"
         :style="{ background: color }">
      <span class="text-xs opacity-75">{{ time }}</span>
      <span class="font-bold text-sm mt-0.5">{{ anchorName }}</span>
    </div>
    <div ref="taskContainer" class="flex-1 bg-white/5 border border-white/10 border-l-0 px-4 py-3">
      <ul
        v-draggable="[anchorPlan.tasks, { group: 'tasks', handle: '.drag-handle', onEnd: onDragEnd }]"
        :data-anchor-id="anchorId"
        :data-date="effectiveDate"
        class="space-y-1">
        <div
          v-for="(task, i) in anchorPlan.tasks"
          :key="task.id || i"
          :data-task-id="task.id">
          <TaskItem
            :task="task"
            @update="onUpdate($event, i)"
            @remove="onRemove(i)" />
        </div>
      </ul>
      <button type="button" @click="onAddNewTask" class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
    </div>
  </div>
</template>
