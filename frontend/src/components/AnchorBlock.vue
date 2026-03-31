<script setup lang="ts">
import { computed } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
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
  const updated = [
    ...anchorPlan.value.tasks,
    {
      id: '',
      text: '',
      status: 'pending' as const,
      position: anchorPlan.value.tasks.length,
      followup_config: null,
      blocks: [],
      blocked_by: [],
    },
  ]
  store.updateAnchorTasks(props.anchorId, updated, anchorPlan.value.notes ?? '')
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
    <div class="flex-1 bg-white/5 border border-white/10 border-l-0 px-4 py-3">
      <VueDraggable
        :modelValue="anchorPlan.tasks"
        group="tasks"
        item-key="id"
        :data-anchor-id="anchorId"
        :data-date="effectiveDate"
        @end="onDragEnd"
        tag="ul"
        class="space-y-1">
        <template #item="{ element: task, index: i }">
          <div :data-task-id="task.id">
            <TaskItem
              :task="task"
              @update="onUpdate($event, i)"
              @remove="onRemove(i)" />
          </div>
        </template>
      </VueDraggable>
      <button type="button" @click="onAddNewTask" class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
    </div>
  </div>
</template>
