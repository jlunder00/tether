<script setup lang="ts">
import { computed, ref } from 'vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { KanbanColumn } from '../stores/kanban'
import { api } from '../lib/api'
import { useDropZone } from '../composables/useDropZone'
import { useSlideOver } from '../composables/useSlideOver'

const { push: pushPanel } = useSlideOver()

const props = defineProps<{
  column: KanbanColumn
  tasks: Task[]
}>()

const emit = defineEmits<{
  (e: 'add-task', opts: { context_subject?: string; milestone_id?: string }): void
  (e: 'task-drop', taskId: string, columnId: string): void
}>()

const STATUS_MOTIF: Record<string, string> = {
  pending: 'quiet',     todo:  'quiet',
  in_progress: 'focus', doing: 'focus',
  done: 'calm',
  skipped: 'dusk',      skip:  'dusk',
  blocked: 'energy',    block: 'energy',
}

const columnMotif = computed(() => {
  const matchStatus = (props.column.match_rules as { status?: unknown } | null)?.status
  const entryStatus = (props.column.entry_rules as { set_status?: unknown } | null)?.set_status
  const status = (typeof matchStatus === 'string' && matchStatus)
    || (typeof entryStatus === 'string' && entryStatus)
  return (status && STATUS_MOTIF[status]) || 'anchor'
})

async function onTaskUpdate(task: Task) {
  // Patch via API — status change, text change, etc.
  await api(`/api/tasks/${task.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: task.status, text: task.text }),
  })
  // KanbanView will re-render via reactive stores
}

const milestoneStore = useMilestoneStore()

/** Group tasks by context (node_id for uniqueness, subject for label), then by milestone */
const grouped = computed(() => {
  const byContext: Record<string, { label: string; contextSubject: string | null; tasks: Task[] }> = {}
  for (const task of props.tasks) {
    const key = task.context_node_id ?? task.context_subject ?? '__uncategorized__'
    if (!byContext[key]) {
      const isUncat = key === '__uncategorized__'
      const label = task.context_subject ?? (isUncat ? 'Uncategorized' : key)
      byContext[key] = { label, contextSubject: isUncat ? null : (task.context_subject ?? null), tasks: [] }
    }
    byContext[key].tasks.push(task)
  }
  // Sort: Uncategorized last
  const sorted = Object.entries(byContext).sort(([, a], [, b]) => {
    if (a.label === 'Uncategorized') return 1
    if (b.label === 'Uncategorized') return -1
    return a.label.localeCompare(b.label)
  })

  return sorted.map(([, { label, contextSubject, tasks }]) => {
    // Sub-group by milestone
    const byMilestone: Record<string, { id: string; name: string; color: string | null; tasks: Task[] }> = {}
    const ungrouped: Task[] = []

    for (const task of tasks) {
      const milestones = milestoneStore.taskMilestones[task.id]
      if (milestones?.length) {
        const m = milestones[0]
        if (!byMilestone[m.id]) byMilestone[m.id] = { id: m.id, name: m.name, color: m.color, tasks: [] }
        byMilestone[m.id].tasks.push(task)
      } else {
        ungrouped.push(task)
      }
    }

    return {
      label,
      contextSubject,
      tasks,
      milestoneGroups: Object.values(byMilestone),
      ungrouped,
    }
  })
})

function addOpts(contextSubject: string | null, milestoneId?: string) {
  const opts: { context_subject?: string; milestone_id?: string } = {}
  if (contextSubject) opts.context_subject = contextSubject
  if (milestoneId) opts.milestone_id = milestoneId
  return opts
}

// ── Source hiding ─────────────────────────────────────────────────────────────
// Track which task is being dragged so its wrapper div can be hidden via v-show.
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
  }))
}

function onTaskDragEnd() {
  draggingTaskId.value = null
}

// ── Drop target — useDropZone replaces manual dragEnterCount ─────────────────
const { isOver, dropHandlers } = useDropZone({
  onDrop(payload) {
    if (
      payload !== null &&
      typeof payload === 'object' &&
      'taskId' in payload &&
      typeof (payload as Record<string, unknown>).taskId === 'string'
    ) {
      emit('task-drop', (payload as { taskId: string }).taskId, props.column.id)
    }
  },
})
</script>

<template>
  <div :data-motif="columnMotif" class="relative flex flex-col min-w-[320px] max-w-[380px] bg-[--bg-elev-1] border border-[--border-1] rounded-xl flex-shrink-0 min-h-0">
    <div class="absolute left-0 top-2 bottom-2 w-0.5 rounded-full pointer-events-none" :style="{ background: 'var(--m)' }" />
    <!-- Column header (fixed, does not scroll) -->
    <div class="flex items-center gap-2 px-3 py-2.5 border-b border-[--border-1] bg-[--bg-elev-2] flex-shrink-0">
      <span v-if="column.color" class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: column.color }" />
      <span class="text-sm font-semibold uppercase tracking-wide text-[--fg-1]"
            :style="column.color ? { color: column.color } : {}">
        {{ column.name }}
      </span>
      <span class="text-xs text-[--fg-5] ml-auto">{{ tasks.length }}</span>
    </div>

    <!-- Scrollable body (fills remaining column height) -->
    <div class="flex-1 overflow-y-auto p-2 space-y-2 min-h-0 transition-all"
         :class="isOver ? 'ring-2 ring-[--accent] bg-[--accent-veil]' : ''"
         @dragenter="dropHandlers.onDragEnter"
         @dragover="dropHandlers.onDragOver"
         @dragleave="dropHandlers.onDragLeave"
         @drop="dropHandlers.onDrop">
      <template v-if="!tasks.length">
        <p class="text-[--fg-6] text-xs text-center py-4">No tasks</p>
      </template>

      <template v-for="group in grouped" :key="group.label">
        <GroupContainer :label="group.label" :collapsible="true" :level="0" :stickyOffset="0">
          <template #header-right>
            <span class="text-xs text-[--fg-5]">{{ group.tasks.length }}</span>
          </template>

          <!-- Milestone sub-groups -->
          <GroupContainer
            v-for="mg in group.milestoneGroups"
            :key="mg.name"
            :label="mg.name"
            :color="mg.color ?? undefined"
            :level="1"
            :stickyOffset="0"
            class="mb-1"
            @header-click="pushPanel({ kind: 'milestone', entityId: mg.id })">
            <div class="space-y-px">
              <div
                v-for="task in mg.tasks"
                :key="task.id"
                :data-task-id="task.id"
                draggable="true"
                v-show="draggingTaskId !== task.id"
                @dragstart="onTaskDragStart($event, task)"
                @dragend="onTaskDragEnd"
              >
                <TaskCard
                  :task="task"
                  :editable="false"
                  :showRemove="false"
                  :compact="true" :hideTags="true"
                  @update="onTaskUpdate" />
              </div>
            </div>
            <button @click.stop="emit('add-task', addOpts(group.contextSubject, mg.id))"
                    class="mt-1 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
              + Add task
            </button>
          </GroupContainer>

          <!-- Ungrouped tasks -->
          <div v-if="group.ungrouped.length" class="space-y-1">
            <div
              v-for="task in group.ungrouped"
              :key="task.id"
              :data-task-id="task.id"
              draggable="true"
              v-show="draggingTaskId !== task.id"
              @dragstart="onTaskDragStart($event, task)"
              @dragend="onTaskDragEnd"
            >
              <TaskCard
                :task="task"
                :editable="false"
                :showRemove="false"
                :compact="true" :hideTags="true"
                @update="onTaskUpdate" />
            </div>
          </div>

          <button @click.stop="emit('add-task', addOpts(group.contextSubject))"
                  class="mt-1 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
            + Add task
          </button>
        </GroupContainer>
      </template>

      <button @click="emit('add-task', {})" class="mt-2 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
        + Add task
      </button>
    </div>
  </div>
</template>
