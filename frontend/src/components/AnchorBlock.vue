<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { Milestone } from '../stores/milestones'

const router = useRouter()

const props = defineProps<{
  anchorId: string
  anchorName: string
  time: string
  color: string
  date?: string
}>()

const store = usePlanStore()
const tasksRef = ref<HTMLElement | null>(null)
const effectiveDate = computed(() => props.date ?? store.activeDate)
const dayPlan = computed(() => props.date ? store.plans[props.date] : store.plan)
const anchorPlan = computed(() => dayPlan.value?.anchors[props.anchorId] ?? { tasks: [], notes: '' })

const milestoneStore = useMilestoneStore()

type TaskWithIndex = { task: Task; index: number }

const groupedByContext = computed(() => {
  const byContext: Record<string, {
    label: string
    milestoneGroups: { milestone: Milestone; tasks: TaskWithIndex[] }[]
    ungrouped: TaskWithIndex[]
  }> = {}

  anchorPlan.value.tasks.forEach((task, index) => {
    const key = task.context_node_id ?? task.context_subject ?? '__uncategorized__'
    if (!byContext[key]) {
      const label = task.context_subject ?? (key === '__uncategorized__' ? 'Uncategorized' : key)
      byContext[key] = { label, milestoneGroups: [], ungrouped: [] }
    }
    const ctx = key

    const milestones = milestoneStore.taskMilestones[task.id]
    if (milestones?.length) {
      const m = milestones[0]
      let group = byContext[ctx].milestoneGroups.find(g => g.milestone.id === m.id)
      if (!group) {
        group = { milestone: m, tasks: [] }
        byContext[ctx].milestoneGroups.push(group)
      }
      group.tasks.push({ task, index })
    } else {
      byContext[ctx].ungrouped.push({ task, index })
    }
  })

  return Object.entries(byContext).sort(([, a], [, b]) => {
    if (a.label === 'Uncategorized') return 1
    if (b.label === 'Uncategorized') return -1
    return a.label.localeCompare(b.label)
  })
})

function contextTaskCount(ctx: { milestoneGroups: { tasks: TaskWithIndex[] }[]; ungrouped: TaskWithIndex[] }): number {
  return ctx.milestoneGroups.reduce((sum, g) => sum + g.tasks.length, 0) + ctx.ungrouped.length
}

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
    context_node_id: null,
  })
  nextTick(() => {
    const inputs = tasksRef.value?.querySelectorAll('input')
    if (inputs?.length) (inputs[inputs.length - 1] as HTMLInputElement).focus()
  })
}

// ── Drag and drop (native HTML5 DnD) ─────────────────────────────────────────
// Drag handle removed; these handlers remain on wrapper divs for future card-level DnD.

function onDragStart(evt: DragEvent, task: Task) {
  if (!task.id) { evt.preventDefault(); return }
  evt.dataTransfer!.effectAllowed = 'move'
  evt.dataTransfer!.setData('text/plain', JSON.stringify({
    taskId: task.id,
    fromAnchorId: props.anchorId,
    fromDate: effectiveDate.value,
  }))
}

function onDrop(evt: DragEvent, toIndex: number) {
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

    <div ref="tasksRef" class="space-y-1">
      <template v-for="[ctxName, ctx] in groupedByContext" :key="ctxName">
        <!-- Context has only 1 task total — show standalone (no context GroupContainer) -->
        <template v-if="contextTaskCount(ctx) === 1">
          <template v-for="mg in ctx.milestoneGroups" :key="mg.milestone.id">
            <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                 :data-task-id="task.id"
                 @dragstart="onDragStart($event, task)"
                 @dragover.prevent
                 @drop.stop.prevent="onDrop($event, i)">
              <TaskCard class="min-w-0" :task="task" :hideTags="false"
                        @update="onUpdate($event, i)" @remove="onRemove(i)" />
            </div>
          </template>
          <div v-for="{ task, index: i } in ctx.ungrouped" :key="task.id || i"
               :data-task-id="task.id"
               @dragstart="onDragStart($event, task)"
               @dragover.prevent
               @drop.stop.prevent="onDrop($event, i)">
            <TaskCard class="min-w-0" :task="task" :hideTags="false"
                      @update="onUpdate($event, i)" @remove="onRemove(i)" />
          </div>
        </template>

        <!-- Context has >1 task — wrap in context GroupContainer -->
        <GroupContainer v-else :label="ctx.label" :collapsible="true" :level="1" class="mb-2">
          <!-- Milestone sub-groups -->
          <template v-for="mg in ctx.milestoneGroups" :key="mg.milestone.id">
            <!-- Milestone group has 1 task — show standalone with tags visible -->
            <template v-if="mg.tasks.length === 1">
              <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                   :data-task-id="task.id"
                   @dragstart="onDragStart($event, task)"
                   @dragover.prevent
                   @drop.stop.prevent="onDrop($event, i)">
                <TaskCard class="min-w-0" :task="task" :hideTags="false"
                          @update="onUpdate($event, i)" @remove="onRemove(i)" />
              </div>
            </template>
            <!-- Milestone group has >1 task — wrap in milestone GroupContainer -->
            <GroupContainer v-else
              :label="mg.milestone.name"
              :color="mg.milestone.color ?? undefined"
              :level="1"
              class="mb-1"
              @header-click="router.push(`/plan/day/${effectiveDate}/milestone/${mg.milestone.id}`)">
              <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                   :data-task-id="task.id"
                   @dragstart="onDragStart($event, task)"
                   @dragover.prevent
                   @drop.stop.prevent="onDrop($event, i)">
                <TaskCard class="min-w-0" :task="task" :hideTags="true"
                          @update="onUpdate($event, i)" @remove="onRemove(i)" />
              </div>
            </GroupContainer>
          </template>

          <!-- Ungrouped tasks within this context -->
          <div v-for="{ task, index: i } in ctx.ungrouped" :key="task.id || i"
               :data-task-id="task.id"
               @dragstart="onDragStart($event, task)"
               @dragover.prevent
               @drop.stop.prevent="onDrop($event, i)">
            <TaskCard class="min-w-0" :task="task" :hideTags="true"
                      @update="onUpdate($event, i)" @remove="onRemove(i)" />
          </div>
        </GroupContainer>
      </template>
    </div>

    <button type="button" @click="onAddNewTask"
            class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
  </GroupContainer>
</template>
