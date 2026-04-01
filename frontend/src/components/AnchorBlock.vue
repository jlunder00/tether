<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import TaskItem from './TaskItem.vue'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'

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
const debugMsg = ref('')
const effectiveDate = computed(() => props.date ?? store.activeDate)
const dayPlan = computed(() => props.date ? store.plans[props.date] : store.plan)
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
  const effectivePlan = props.date ? store.plans[props.date] : store.plan
  if (!effectivePlan) return
  if (!effectivePlan.anchors[props.anchorId]) {
    effectivePlan.anchors[props.anchorId] = { tasks: [], notes: '' }
  }
  const tasks = effectivePlan.anchors[props.anchorId].tasks
  tasks.push({
    id: '', text: '', status: 'pending' as const,
    position: tasks.length, followup_config: null, blocks: [], blocked_by: [],
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
  debugMsg.value = `drop raw=${raw?.slice(0, 60)}`
  setTimeout(() => { debugMsg.value = '' }, 3000)
  if (!raw) return
  try {
    const { taskId, fromAnchorId, fromDate } = JSON.parse(raw)
    if (!taskId) return
    debugMsg.value = `move ${taskId.slice(0,8)} from=${fromAnchorId} to=${props.anchorId} idx=${toIndex}`
    setTimeout(() => { debugMsg.value = '' }, 5000)
    if (fromAnchorId === props.anchorId && fromDate === effectiveDate.value) {
      store.reorderTask(taskId, effectiveDate.value, props.anchorId, toIndex)
    } else {
      store.moveTask(taskId, fromDate, fromAnchorId, effectiveDate.value, props.anchorId, toIndex)
    }
  } catch (e) { debugMsg.value = `error: ${e}`; }
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
      <div v-if="debugMsg" class="text-xs text-yellow-300 mb-1">{{ debugMsg }}</div>
      <ul
        ref="ulRef"
        class="space-y-1 min-h-[2rem] rounded transition-colors"
        :class="dragOver ? 'bg-white/10 ring-2 ring-white/30' : ''"
        @dragover.prevent="onDragOver"
        @dragleave="onDragLeave"
        @drop.prevent="onDrop($event, anchorPlan.tasks.length)">
        <div
          v-for="(task, i) in anchorPlan.tasks"
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
          <TaskItem
            class="flex-1 min-w-0"
            :task="task"
            @update="onUpdate($event, i)"
            @remove="onRemove(i)" />
        </div>
      </ul>
      <button type="button" @click="onAddNewTask"
              class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
    </div>
  </div>
</template>
