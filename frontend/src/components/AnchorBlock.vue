<script setup lang="ts">
import { computed, ref } from 'vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import MotifPicker, { type MotifSlot } from './MotifPicker.vue'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { Milestone } from '../stores/milestones'
import { api } from '../lib/api'
import { useDropZone } from '../composables/useDropZone'
import { useSlideOver } from '../composables/useSlideOver'

const { push: pushPanel } = useSlideOver()

const props = defineProps<{
  anchorId: string
  anchorName: string
  time: string
  color: string
  date?: string
  motif?: string | null
  isNow?: boolean
  isPast?: boolean
  isLast?: boolean
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
    contextSubject: string | null
    milestoneGroups: { milestone: Milestone; tasks: TaskWithIndex[] }[]
    ungrouped: TaskWithIndex[]
  }> = {}

  anchorPlan.value.tasks.forEach((task, index) => {
    const key = task.context_node_id ?? task.context_subject ?? '__uncategorized__'
    if (!byContext[key]) {
      const isUncat = key === '__uncategorized__'
      const label = task.context_subject ?? (isUncat ? 'Uncategorized' : key)
      byContext[key] = { label, contextSubject: isUncat ? null : (task.context_subject ?? null), milestoneGroups: [], ungrouped: [] }
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

// Local cache of motif selections per context subject.
// TODO(motif-db-api): backend read path not yet wired. When the parallel
// `feature/motif-db-api` stream ships a `motif` field on context-entry responses,
// seed this map from there (e.g. via a context store) so picks survive remount.
// Until then, selections are lost on reload — acceptable per spec.
const contextMotifs = ref<Record<string, MotifSlot>>({})

async function setContextMotif(subject: string | null, slot: MotifSlot) {
  if (!subject) return
  contextMotifs.value = { ...contextMotifs.value, [subject]: slot }
  try {
    await api(`/api/context/${encodeURIComponent(subject)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ motif: slot }),
    })
  } catch (e) {
    // Backend motif support pending (feature/motif-db-api). Log so non-network
    // failures (bad JSON, undefined subject, etc.) remain visible during dev.
    console.warn('setContextMotif failed:', e)
  }
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

async function onAddNewTask(opts: { context_subject?: string; milestone_id?: string } = {}) {
  const body: Record<string, unknown> = {
    text: 'New task',
    date: effectiveDate.value,
    anchor_id: props.anchorId,
    ...opts,
  }
  try {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok) throw new Error(`${resp.status}`)
    await store.fetchPlan(effectiveDate.value)
  } catch (e) {
    console.error('Failed to create task:', e)
  }
}

// ── Drag and drop (native HTML5 DnD) ─────────────────────────────────────────

// Track which task is being dragged for source hiding via v-show.
const draggingTaskId = ref<string | null>(null)

function onDragStart(evt: DragEvent, task: Task) {
  if (!task.id) { evt.preventDefault(); return }
  if (!evt.dataTransfer) return
  evt.dataTransfer.effectAllowed = 'move'
  // Superset payload — includes type + title for composable compatibility
  evt.dataTransfer.setData('text/plain', JSON.stringify({
    type: 'task',
    taskId: task.id,
    title: task.text,
    fromAnchorId: props.anchorId,
    fromDate: effectiveDate.value,
  }))
  // Defer source-hiding to rAF so the browser can capture a visible ghost image.
  // Setting draggingTaskId synchronously causes Vue's microtask DOM update to apply
  // display:none before Chrome snapshots the ghost — resulting in no visible ghost.
  requestAnimationFrame(() => { draggingTaskId.value = task.id })
}

function onDragEnd() {
  draggingTaskId.value = null
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

// ── Container-level drop zone (fixes empty-anchor drop bug) ──────────────────
// When anchor has no tasks, there are no per-task wrapper drop zones. The
// container drop zone catches those drops and appends the task.
const { isOver: isContainerOver, dropHandlers: containerDropHandlers } = useDropZone({
  onDrop(payload) {
    const p = payload as { taskId?: string; fromAnchorId?: string; fromDate?: string }
    if (!p.taskId) return
    const toIndex = anchorPlan.value.tasks.length
    if (p.fromAnchorId === props.anchorId && p.fromDate === effectiveDate.value) {
      store.reorderTask(p.taskId, effectiveDate.value, props.anchorId, toIndex)
    } else {
      store.moveTask(p.taskId, p.fromDate ?? '', p.fromAnchorId ?? '', effectiveDate.value, props.anchorId, toIndex)
    }
  },
})
</script>

<template>
  <div :data-motif="motif ?? 'anchor'" class="anchor-row">
    <!-- Rail: dot + connecting line -->
    <div class="anchor-rail">
      <div
        data-testid="anchor-dot"
        class="anchor-dot"
        :class="{
          'anchor-dot--now': isNow,
          'anchor-dot--past': isPast,
          'anchor-dot--upcoming': !isNow && !isPast,
        }"
      />
      <div
        v-if="!isLast"
        data-testid="anchor-line"
        class="anchor-line"
      />
    </div>

    <!-- Card content — also serves as the container-level drop zone for empty anchors -->
    <div class="min-w-0 transition-colors rounded"
         :class="isContainerOver ? 'ring-1 ring-[--accent] bg-[--accent-veil]' : ''"
         @dragenter="containerDropHandlers.onDragEnter"
         @dragover="containerDropHandlers.onDragOver"
         @dragleave="containerDropHandlers.onDragLeave"
         @drop="containerDropHandlers.onDrop">
  <GroupContainer :label="`${anchorName} · ${time}`" :collapsible="true" :level="0">
    <template #header-right>
      <span class="text-xs text-[--fg-5]">{{ anchorPlan.tasks.length }}</span>
    </template>

    <div ref="tasksRef" class="space-y-px">
      <template v-for="[ctxName, ctx] in groupedByContext" :key="ctxName">
        <!-- Context has only 1 task total — show standalone (no context GroupContainer) -->
        <template v-if="contextTaskCount(ctx) === 1">
          <template v-for="mg in ctx.milestoneGroups" :key="mg.milestone.id">
            <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                 :data-task-id="task.id"
                 draggable="true"
                 v-show="draggingTaskId !== task.id"
                 @dragstart="onDragStart($event, task)"
                 @dragend="onDragEnd"
                 @dragover.prevent
                 @drop.stop.prevent="onDrop($event, i)">
              <TaskCard class="min-w-0" :task="task" :hideTags="false"
                        @update="onUpdate($event, i)" @remove="onRemove(i)" />
            </div>
          </template>
          <div v-for="{ task, index: i } in ctx.ungrouped" :key="task.id || i"
               :data-task-id="task.id"
               draggable="true"
               v-show="draggingTaskId !== task.id"
               @dragstart="onDragStart($event, task)"
               @dragend="onDragEnd"
               @dragover.prevent
               @drop.stop.prevent="onDrop($event, i)">
            <TaskCard class="min-w-0" :task="task" :hideTags="false"
                      @update="onUpdate($event, i)" @remove="onRemove(i)" />
          </div>
        </template>

        <!-- Context has >1 task — wrap in context GroupContainer with motif sidebar -->
        <div v-else class="relative">
          <div
            v-if="ctx.contextSubject && contextMotifs[ctx.contextSubject]"
            class="absolute left-0 top-0 bottom-0 w-0.5 pointer-events-none"
            :style="{ background: `var(--motif-${contextMotifs[ctx.contextSubject]})` }"
          />
        <GroupContainer :label="ctx.label" :collapsible="true" :level="1" class="mb-2 group/ctx">
          <template #header-right>
            <div
              v-if="ctx.contextSubject"
              data-testid="context-motif-picker"
              class="opacity-0 group-hover/ctx:opacity-100 transition-opacity ml-1"
              @click.stop>
              <MotifPicker
                :model-value="contextMotifs[ctx.contextSubject] ?? null"
                @update:model-value="(slot) => setContextMotif(ctx.contextSubject, slot)"
              />
            </div>
          </template>
          <!-- Milestone sub-groups -->
          <template v-for="mg in ctx.milestoneGroups" :key="mg.milestone.id">
            <!-- Milestone group has 1 task — show standalone with tags visible -->
            <template v-if="mg.tasks.length === 1">
              <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                   :data-task-id="task.id"
                   draggable="true"
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
              class="mb-1 group/milestone"
              @header-click="pushPanel({ kind: 'milestone', entityId: mg.milestone.id })">
              <template #header-right>
                <div
                  data-testid="milestone-motif-picker"
                  class="opacity-0 group-hover/milestone:opacity-100 transition-opacity ml-1"
                  @click.stop>
                  <MotifPicker
                    :model-value="(mg.milestone.motif as MotifSlot | null | undefined) ?? null"
                    @update:model-value="(slot) => milestoneStore.patchMilestone(mg.milestone.id, { motif: slot })"
                  />
                </div>
              </template>
              <div v-for="{ task, index: i } in mg.tasks" :key="task.id || i"
                   :data-task-id="task.id"
                   draggable="true"
                   @dragstart="onDragStart($event, task)"
                   @dragover.prevent
                   @drop.stop.prevent="onDrop($event, i)">
                <TaskCard class="min-w-0" :task="task" :hideTags="true"
                          @update="onUpdate($event, i)" @remove="onRemove(i)" />
              </div>
              <button type="button"
                      @click.stop="onAddNewTask({ ...(ctx.contextSubject ? { context_subject: ctx.contextSubject } : {}), milestone_id: mg.milestone.id })"
                      class="mt-1 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
                + Add task
              </button>
            </GroupContainer>
          </template>

          <!-- Ungrouped tasks within this context -->
          <div v-for="{ task, index: i } in ctx.ungrouped" :key="task.id || i"
               :data-task-id="task.id"
               draggable="true"
               @dragstart="onDragStart($event, task)"
               @dragover.prevent
               @drop.stop.prevent="onDrop($event, i)">
            <TaskCard class="min-w-0" :task="task" :hideTags="true"
                      @update="onUpdate($event, i)" @remove="onRemove(i)" />
          </div>

          <button type="button"
                  @click.stop="onAddNewTask(ctx.contextSubject ? { context_subject: ctx.contextSubject } : {})"
                  class="mt-1 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
            + Add task
          </button>
        </GroupContainer>
        </div>
      </template>
    </div>

    <button type="button" @click="onAddNewTask()"
            class="mt-2 text-xs text-[--fg-4] hover:text-[--fg-2]">+ Add task</button>
  </GroupContainer>
    </div><!-- end card content -->
  </div><!-- end anchor-row -->
</template>

<style scoped>
/* ── Anchor row: rail column + card column ── */
.anchor-row {
  display: grid;
  grid-template-columns: 24px 1fr;
  gap: 12px;
  padding-bottom: 8px; /* matches gap between rows */
}

/* Rail: vertically stacked dot + line */
.anchor-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 10px;
  position: relative;
  overflow: visible;
}

/* Connecting line */
.anchor-line {
  flex: 1;
  width: var(--line-strength, 2px);
  background: var(--m, var(--line-color));
  opacity: 0.55;
  margin-top: 4px;
  /* Extend 8px past the component to bridge the padding-bottom gap */
  margin-bottom: -8px;
  min-height: 16px;
}

/* Base dot */
.anchor-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--m, var(--line-color));
  flex-shrink: 0;
  position: relative;
  z-index: 1;
}

/* Now: larger with glow ring */
.anchor-dot--now {
  width: 16px;
  height: 16px;
  box-shadow:
    0 0 0 4px var(--bg-canvas),
    0 0 0 6px var(--m-line, var(--line-glow)),
    0 0 14px 2px var(--m-line, var(--line-glow));
}

/* Past: faded */
.anchor-dot--past {
  opacity: 0.35;
}

/* Upcoming: slightly faded */
.anchor-dot--upcoming {
  opacity: 0.55;
}

/* Terminal theme: square nodes + dashed line */
[data-theme="terminal"] .anchor-dot {
  border-radius: 2px;
  border: 1px solid var(--m, rgba(80, 250, 123, 0.5));
  background: var(--bg-canvas);
}
[data-theme="terminal"] .anchor-dot--now {
  background: var(--m, var(--accent));
}
[data-theme="terminal"] .anchor-line {
  background: none;
  border-left: 1.5px dashed var(--m, rgba(80, 250, 123, 0.35));
  width: 0;
}
</style>
