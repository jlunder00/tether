<script setup lang="ts">
import { computed, ref } from 'vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { KanbanColumn } from '../stores/kanban'
import { api } from '../lib/api'
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

// ── Drop target (dragenter counter avoids highlight flicker on child elements) ──

const dragEnterCount = ref(0)

function onColumnDragEnter() {
  dragEnterCount.value++
}

function onColumnDragOver(evt: DragEvent) {
  evt.preventDefault()
  if (evt.dataTransfer) {
    evt.dataTransfer.dropEffect = 'move'
  }
}

function onColumnDragLeave() {
  dragEnterCount.value = Math.max(0, dragEnterCount.value - 1)
}

function onColumnDrop(evt: DragEvent) {
  evt.preventDefault()
  evt.stopPropagation()
  dragEnterCount.value = 0
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return // ignore drops from external sources (files, other apps)
  }

  if (
    parsed !== null &&
    typeof parsed === 'object' &&
    'taskId' in parsed &&
    typeof (parsed as Record<string, unknown>).taskId === 'string'
  ) {
    emit('task-drop', (parsed as { taskId: string }).taskId, props.column.id)
  }
}
</script>

<template>
  <div class="flex flex-col min-w-[320px] max-w-[380px] bg-[--bg-elev-1] border border-[--border-1] rounded-xl flex-shrink-0 min-h-0">
    <!-- Column header (fixed, does not scroll) -->
    <div class="flex items-center gap-2 px-3 py-2.5 border-b border-[--border-1] flex-shrink-0">
      <span v-if="column.color" class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: column.color }" />
      <span class="text-sm font-semibold uppercase tracking-wide"
            :style="column.color ? { color: column.color } : {}">
        {{ column.name }}
      </span>
      <span class="text-xs text-[--fg-5] ml-auto">{{ tasks.length }}</span>
    </div>

    <!-- Scrollable body (fills remaining column height) -->
    <div class="flex-1 overflow-y-auto p-2 space-y-2 min-h-0 transition-all"
         :class="dragEnterCount > 0 ? 'ring-2 ring-blue-400/50 bg-blue-400/5' : ''"
         @dragenter="onColumnDragEnter"
         @dragover="onColumnDragOver"
         @dragleave="onColumnDragLeave"
         @drop="onColumnDrop">
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
              <TaskCard
                v-for="task in mg.tasks"
                :key="task.id"
                :task="task"
                :editable="false"
                :showRemove="false"
                :compact="true" :hideTags="true"
                @update="onTaskUpdate" />
            </div>
            <button @click.stop="emit('add-task', addOpts(group.contextSubject, mg.id))"
                    class="mt-1 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
              + Add task
            </button>
          </GroupContainer>

          <!-- Ungrouped tasks -->
          <div v-if="group.ungrouped.length" class="space-y-1">
            <TaskCard
              v-for="task in group.ungrouped"
              :key="task.id"
              :task="task"
              :editable="false"
              :showRemove="false"
              :compact="true" :hideTags="true"
              @update="onTaskUpdate" />
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
