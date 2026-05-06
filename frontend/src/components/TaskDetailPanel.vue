<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../lib/api'
import SearchAutocomplete from './SearchAutocomplete.vue'
import RecurrencePicker from './RecurrencePicker.vue'
import RecurrenceEditDialog from './RecurrenceEditDialog.vue'
import MotifPicker, { type MotifSlot } from './MotifPicker.vue'
import type { SearchResult } from './SearchAutocomplete.vue'
import { usePlanStore } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import { useAnchorStore } from '../stores/anchors'
import { useBacklogStore } from '../stores/backlog'
import { useEventStore } from '../stores/events'
import { useTasksStore } from '../stores/tasks'
import { useKanbanStore } from '../stores/kanban'
import { useSubtasks } from '../composables/useSubtasks'
import { useLinks } from '../composables/useLinks'
import { useDependencies } from '../composables/useDependencies'
import { useTaskContexts } from '../composables/useTaskContexts'
import { useSlideOver } from '../composables/useSlideOver'
import type { TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import type { RecurrenceEditScope } from '../types/recurrence'

const props = defineProps<{ taskId: string }>()
const { push: pushPanel, pop: popPanel } = useSlideOver()
const planStore = usePlanStore()
const milestoneStore = useMilestoneStore()
const anchorStore = useAnchorStore()
const backlogStore = useBacklogStore()
const eventStore = useEventStore()
const tasksStore = useTasksStore()
const kanbanStore = useKanbanStore()

// Calendar event linked to this task, OR the event itself when props.taskId is an event ID
// (standalone events opened via kind:'event' in SlideOverStack pass event.id as taskId).
const taskEvent = computed(
  () =>
    eventStore.events.find(e => e.task_id === props.taskId) ??
    eventStore.events.find(e => e.id === props.taskId) ??
    null,
)

// Find the task from the plan OR from the backlog
const taskAndAnchor = computed(() => {
  if (planStore.plan) {
    for (const [aid, anchorPlan] of Object.entries(planStore.plan.anchors)) {
      const t = anchorPlan.tasks.find(t => t.id === props.taskId)
      if (t) return { task: t, anchorId: aid, isBacklog: false }
    }
  }
  const bt = backlogStore.tasks.find(t => t.id === props.taskId)
  if (bt) return { task: bt, anchorId: '', isBacklog: true }
  // Also check standalone fetch
  if (standaloneTask.value) return { task: standaloneTask.value, anchorId: '', isBacklog: true }
  return null
})

const task = computed(() => taskAndAnchor.value?.task ?? null)
const anchorId = computed(() => taskAndAnchor.value?.anchorId ?? '')
const isBacklog = computed(() => taskAndAnchor.value?.isBacklog ?? false)

// Standalone task fetch for when task isn't in plan or backlog store yet
const standaloneTask = ref<any>(null)

// Schedule controls (backlog → plan)
const scheduleDate = ref(planStore.today)
const scheduleAnchor = ref('')

// Reschedule controls (plan → different date/anchor)
// Tracks the date of the plan the task currently lives in.
const taskPlanDate = computed(() => planStore.plan?.date ?? planStore.today)

// Composables
const { subtasks, create: createSubtask, update: updateSubtask, remove: removeSubtask } = useSubtasks(() => props.taskId)
const { links, create: createLink, remove: removeLink } = useLinks(() => 'tasks', () => props.taskId)
const { deps, add: addDep, remove: removeDep } = useDependencies(() => 'task', () => props.taskId)
const { contexts, link: linkContext, unlink: unlinkContext } = useTaskContexts(() => props.taskId)

// Subtasks
const newSubtaskText = ref('')
const subtasksDone = computed(() => subtasks.value.filter(s => s.done).length)

async function addSubtask() {
  const text = newSubtaskText.value.trim()
  if (!text) return
  newSubtaskText.value = ''
  await createSubtask(text)
}

// Links
const showAddLink = ref(false)
const newLinkUrl = ref('')
const newLinkLabel = ref('')
const newLinkCategory = ref('other')

const LINK_ICONS: Record<string, string> = {
  document: '📄',
  meeting: '🔗',
  pr: '⚡',
  issue: '🐛',
  other: '📎',
}

async function addLink() {
  const url = newLinkUrl.value.trim()
  if (!url) return
  await createLink(url, newLinkLabel.value.trim() || null, newLinkCategory.value)
  newLinkUrl.value = ''
  newLinkLabel.value = ''
  newLinkCategory.value = 'other'
  showAddLink.value = false
}

// Task PATCH helper — routes through the plan store (standing rule: no api() in components)
async function patchTask(fields: Record<string, unknown>) {
  const ok = await planStore.patchTaskFields(props.taskId, fields)
  // Optimistic in-place merge for objects not tracked in the plan store
  // (standalone events on non-current dates, backlog tasks).
  if (ok && task.value) Object.assign(task.value, fields)
  if (isBacklog.value) {
    await backlogStore.fetchTasks()
  } else {
    await planStore.fetchPlan()
  }
  // Mirror the patch into the kanban store so the kanban view re-renders
  // when fields like motif/text/status are edited from the detail panel.
  if (ok) kanbanStore.applyTaskPatch(props.taskId, fields)
}

// Text editing
function onTextChange(e: Event) {
  const text = (e.target as HTMLInputElement).value
  patchTask({ text })
}

// Status
function onStatusChange(e: Event) {
  const status = (e.target as HTMLSelectElement).value as TaskStatus
  patchTask({ status })
}

// Motif
function onMotifChange(slot: MotifSlot) {
  patchTask({ motif: slot })
}

// Description
function onDescBlur(e: Event) {
  const description = (e.target as HTMLTextAreaElement).value || null
  patchTask({ description })
}

// Follow-up config
const showFollowup = ref(false)

function toggleFollowup(enabled: boolean) {
  const fc: FollowupConfig = enabled ? {
    enabled: true,
    pre_ack_interval_min: 5,
    pre_ack_max_pings: 3,
    post_ack_interval_min: 15,
    post_ack_pings: 2,
  } : { enabled: false, pre_ack_interval_min: 5, pre_ack_max_pings: 3, post_ack_interval_min: 15, post_ack_pings: 2 }
  patchTask({ followup_config: enabled ? fc : null })
}

function patchFollowup(fields: Partial<FollowupConfig>) {
  if (!task.value?.followup_config) return
  patchTask({ followup_config: { ...task.value.followup_config, ...fields } })
}

// Schedule / Unschedule
async function scheduleTask() {
  if (!scheduleDate.value || !scheduleAnchor.value) return
  await planStore.scheduleTask(props.taskId, scheduleDate.value, scheduleAnchor.value)
  await planStore.fetchPlan(scheduleDate.value)
  await backlogStore.fetchTasks()
  // Panel stays open — the task has moved, stores refreshed above
}

async function moveToBacklog() {
  await planStore.moveToBacklog(props.taskId)
  await planStore.fetchPlan()
  await backlogStore.fetchTasks()
}

async function moveToAnchor(newAnchorId: string) {
  await planStore.moveTask(props.taskId, taskPlanDate.value, anchorId.value, taskPlanDate.value, newAnchorId)
  await planStore.fetchPlan()
}

async function onRescheduleDate(e: Event) {
  const newDate = (e.target as HTMLInputElement).value
  if (!newDate || newDate === taskPlanDate.value) return
  await planStore.moveTask(props.taskId, taskPlanDate.value, anchorId.value, newDate, anchorId.value)
  // Refresh the current day (no arg) — passing newDate would change activeDate and
  // cause AnchorBlock to show the destination day's content under the wrong URL.
  await planStore.fetchPlan()
}

// Delete
async function deleteTask() {
  if (!confirm('Delete this task?')) return
  await tasksStore.deleteTask(props.taskId)
  // Remove any associated calendar event from local state immediately so the
  // grid updates without waiting for a re-fetch.
  eventStore.removeEventsForTask(props.taskId)
  popPanel()
  if (isBacklog.value) {
    await backlogStore.fetchTasks()
  } else {
    await planStore.fetchPlan()
  }
}

// Navigate to milestone panel (push onto slide-over stack)
function openMilestone(milestoneId: string) {
  pushPanel({ kind: 'milestone', entityId: milestoneId })
}

// Search functions for dependency and milestone linking
async function searchForDependency(q: string): Promise<SearchResult[]> {
  const resp = await api(`/api/search?q=${encodeURIComponent(q)}&type=all`)
  if (!resp.ok) return []
  const items = await resp.json()
  // Exclude self
  return items.filter((i: SearchResult) => i.id !== props.taskId)
}

async function searchForMilestone(q: string): Promise<SearchResult[]> {
  const resp = await api(`/api/search?q=${encodeURIComponent(q)}&type=milestone`)
  if (!resp.ok) return []
  return resp.json()
}

async function addDependencyFromSearch(item: SearchResult) {
  // This task is blocked by the selected item
  await addDep(item.type ?? 'task', item.id, 'task', props.taskId)
}

async function linkMilestoneFromSearch(item: SearchResult) {
  await milestoneStore.linkTask(item.id, props.taskId)
  await milestoneStore.fetchAll()
}

async function searchForContext(q: string): Promise<SearchResult[]> {
  const resp = await api('/api/context')
  if (!resp.ok) return []
  const entries: Array<{ subject: string; body: string }> = await resp.json()
  const lower = q.toLowerCase()
  return entries
    .filter(e => e.subject.toLowerCase().includes(lower))
    .filter(e => !contexts.value.includes(e.subject))
    .map(e => ({ id: e.subject, label: e.subject, type: 'context' }))
}

async function linkContextFromSearch(item: SearchResult) {
  await linkContext(item.id)
}

// Navigate to dependency entity (push onto slide-over stack)
function openDep(type: string, id: string) {
  if (type === 'task') {
    pushPanel({ kind: 'task', entityId: id })
  } else {
    pushPanel({ kind: 'milestone', entityId: id })
  }
}

// Resolve dependency entity_id to a display name
function depLabel(type: string, entityId: string): string {
  if (type === 'milestone') {
    const m = milestoneStore.all.find(m => m.id === entityId)
    if (m) return m.name
  } else {
    // Search today's plan tasks
    if (planStore.plan) {
      for (const anchor of Object.values(planStore.plan.anchors)) {
        const t = anchor.tasks.find(t => t.id === entityId)
        if (t) return t.text
      }
    }
    // Search backlog
    const bt = backlogStore.tasks.find(t => t.id === entityId)
    if (bt) return bt.text
  }
  return entityId.slice(0, 8) + '…'
}

// Calendar time helpers — convert ISO ↔ datetime-local input value (YYYY-MM-DDTHH:MM)
function isoToDatetimeLocal(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function onCalendarStartChange(e: Event) {
  if (!taskEvent.value) return
  const val = (e.target as HTMLInputElement).value
  if (!val) return
  const newStart = new Date(val).toISOString()
  // Preserve original duration
  const dur = new Date(taskEvent.value.end_time).getTime() - new Date(taskEvent.value.start_time).getTime()
  const newEnd = new Date(new Date(val).getTime() + dur).toISOString()
  await eventStore.moveEvent(taskEvent.value.id, newStart, newEnd)
}

async function onCalendarEndChange(e: Event) {
  if (!taskEvent.value) return
  const val = (e.target as HTMLInputElement).value
  if (!val) return
  await eventStore.moveEvent(taskEvent.value.id, taskEvent.value.start_time, new Date(val).toISOString())
}

async function onRecurrenceChange(rrule: string | null) {
  if (!taskEvent.value) return
  await eventStore.setRecurrence(taskEvent.value.id, rrule)
}

// ── Color picker handlers ────────────────────────────────────────────────────
// For non-recurring events: debounce the @input so we PATCH at most once per
// 150 ms instead of once per mouse-move during the color drag.
//
// For recurring events: we must NOT PATCH until the user confirms a scope in
// RecurrenceEditDialog.  @input only buffers a preview value; @change (which
// fires once on picker dismiss) opens the dialog.  The actual PATCH is deferred
// until onColorScopeConfirm().

// Debounce timer — only used for non-recurring events.
let _colorDebounceTimer: ReturnType<typeof setTimeout> | null = null

// Pending color buffered from @input for recurring events (preview-only, no PATCH yet).
const pendingColorValue = ref<string | null | undefined>(undefined)

// Controls whether RecurrenceEditDialog is visible.
const showColorScopeDialog = ref(false)

// The displayed color: pending preview while dialog is open, else the stored value.
// When pendingColorValue is null (reset pending), show the default swatch so
// the picker visually reflects the "clear" state while the dialog is open.
const displayColor = computed(
  () =>
    pendingColorValue.value !== undefined
      ? (pendingColorValue.value ?? '#6366f1')
      : (taskEvent.value?.color ?? '#6366f1'),
)

/** Called on @input for color picker. */
function onColorInput(e: Event) {
  if (!taskEvent.value) return
  const color = (e.target as HTMLInputElement).value
  if (taskEvent.value.rrule) {
    // Recurring: buffer for live preview only — don't PATCH yet.
    pendingColorValue.value = color
  } else {
    // Non-recurring: debounced immediate PATCH.
    if (_colorDebounceTimer !== null) clearTimeout(_colorDebounceTimer)
    _colorDebounceTimer = setTimeout(async () => {
      _colorDebounceTimer = null
      if (taskEvent.value) await eventStore.updateEventColor(taskEvent.value.id, color)
    }, 150)
  }
}

/** Called on @change for color picker (fires once on picker dismiss). */
function onColorChange(e: Event) {
  if (!taskEvent.value) return
  if (!taskEvent.value.rrule) return  // non-recurring already handled by @input
  const color = (e.target as HTMLInputElement).value
  pendingColorValue.value = color
  showColorScopeDialog.value = true
}

/** Called when RecurrenceEditDialog emits 'confirm'. */
async function onColorScopeConfirm(scope: RecurrenceEditScope) {
  showColorScopeDialog.value = false
  const color = pendingColorValue.value ?? null
  pendingColorValue.value = undefined
  if (!taskEvent.value) return
  const originalStartTime = taskEvent.value.is_occurrence
    ? taskEvent.value.start_time
    : undefined
  await eventStore.updateEventColor(taskEvent.value.id, color, scope, originalStartTime)
}

/** Called when RecurrenceEditDialog emits 'cancel' — discard the pending color. */
function onColorScopeCancel() {
  showColorScopeDialog.value = false
  pendingColorValue.value = undefined
}

/** Reset button: clear color immediately for non-recurring; open scope dialog for recurring. */
function onColorReset() {
  if (!taskEvent.value) return
  if (taskEvent.value.rrule) {
    pendingColorValue.value = null
    showColorScopeDialog.value = true
  } else {
    if (_colorDebounceTimer !== null) clearTimeout(_colorDebounceTimer)
    _colorDebounceTimer = setTimeout(async () => {
      _colorDebounceTimer = null
      if (taskEvent.value) await eventStore.updateEventColor(taskEvent.value.id, null)
    }, 150)
  }
}

// ── Anchor-task recurrence (no calendar event) ──────────────────────────────
// For anchor tasks (anchor_id set, no start_time), RecurrencePicker emits
// update:modelValue.  If the task is already a recurring master, we gate
// through RecurrenceEditDialog first; otherwise we PATCH immediately.

// Pending rrule value buffered while the scope dialog is open.
const pendingAnchorRrule = ref<string | null | undefined>(undefined)

// Controls the recurrence-scope dialog for rrule changes on recurring masters.
const showAnchorScopeDialog = ref(false)

// Controls the delete-scope dialog for recurring master deletes.
const showAnchorDeleteDialog = ref(false)

/** Called when RecurrencePicker emits update:modelValue for anchor tasks. */
async function onAnchorRecurrenceChange(rrule: string | null) {
  if (!task.value) return
  if (task.value.is_recurring_master) {
    // Gate behind scope dialog — don't PATCH until user confirms
    pendingAnchorRrule.value = rrule
    showAnchorScopeDialog.value = true
  } else {
    await tasksStore.setTaskRrule(props.taskId, rrule)
    await planStore.fetchPlan()
  }
}

/** Called when anchor recurrence scope dialog confirms. */
async function onAnchorScopeConfirm(_scope: RecurrenceEditScope) {
  showAnchorScopeDialog.value = false
  const rrule = pendingAnchorRrule.value ?? null
  pendingAnchorRrule.value = undefined
  await tasksStore.setTaskRrule(props.taskId, rrule)
  await planStore.fetchPlan()
}

/** Called when anchor recurrence scope dialog cancels. */
function onAnchorScopeCancel() {
  showAnchorScopeDialog.value = false
  pendingAnchorRrule.value = undefined
}

/** Called when the delete button is clicked for anchor tasks. */
async function onDeleteAnchorTask() {
  if (!task.value) return
  if (task.value.is_recurring_master) {
    // Gate through scope dialog for recurring master deletes
    showAnchorDeleteDialog.value = true
  } else {
    await tasksStore.deleteTask(props.taskId)
    popPanel()
    await planStore.fetchPlan()
  }
}

/** Called when anchor delete scope dialog confirms. */
async function onAnchorDeleteConfirm(scope: RecurrenceEditScope) {
  showAnchorDeleteDialog.value = false
  const originalDate = task.value?.original_date
  await tasksStore.deleteTask(props.taskId, scope, originalDate)
  popPanel()
  await planStore.fetchPlan()
}

/** Called when anchor delete scope dialog cancels. */
function onAnchorDeleteCancel() {
  showAnchorDeleteDialog.value = false
}

onMounted(async () => {
  if (!planStore.plan) await planStore.fetchPlan()
  if (!milestoneStore.all.length) await milestoneStore.fetchAll()
  if (!anchorStore.anchors.length) await anchorStore.fetchAnchors()
  if (!backlogStore.tasks.length) await backlogStore.fetchTasks()
  // If task not found in plan or backlog, fetch it directly
  if (!task.value) {
    try {
      const resp = await api(`/api/tasks/${props.taskId}`)
      if (resp.ok) standaloneTask.value = await resp.json()
    } catch { /* task may not exist */ }
  }
  // Default schedule anchor to first anchor
  if (!scheduleAnchor.value && anchorStore.anchors.length) {
    scheduleAnchor.value = anchorStore.anchors[0].id
  }
})
</script>

<template>
  <!-- dp-shell: motif data-attr drives the left-rail colour via --m token -->
  <div class="dp-shell" :data-motif="task?.motif ?? (taskEvent ? 'anchor' : 'anchor')">

    <!-- ── Header ─────────────────────────────────────────────────────────── -->
    <header class="dp-header">
      <div class="dp-crumbs">
        <span class="dp-crumbs__seg">Plan</span>
        <span class="dp-crumbs__sep">›</span>
        <span class="dp-crumbs__seg">{{ planStore.activeDate }}</span>
        <template v-if="anchorId">
          <span class="dp-crumbs__sep">›</span>
          <span class="dp-crumbs__seg">{{ anchorId }}</span>
        </template>
      </div>
      <div class="dp-title-row">
        <template v-if="task">
          <input
            :value="task.text"
            @change="onTextChange"
            class="dp-title"
            placeholder="Task title" />
          <span :class="`t-pill t-pill--${task.status}`">{{ task.status }}</span>
        </template>
        <template v-else-if="taskEvent">
          <span class="dp-title">{{ taskEvent.title }}</span>
        </template>
        <template v-else>
          <span class="dp-title" style="color: var(--fg-5)">Not found</span>
        </template>
      </div>
    </header>

    <!-- ── Scrollable body ────────────────────────────────────────────────── -->
    <div class="dp-body">

      <!-- Not found -->
      <div v-if="!task && !taskEvent" class="dp-section" style="color: var(--fg-5); font-size: 13px;">
        Task not found.
      </div>

      <!-- ── Standalone calendar event (opened via kind:'event') ── -->
      <template v-else-if="!task && taskEvent">
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Calendar</span>
          </header>
          <div class="dp-section__body">
            <div class="dp-field">
              <span class="dp-field__label">Start</span>
              <input type="datetime-local" :value="isoToDatetimeLocal(taskEvent.start_time)"
                     @change="onCalendarStartChange" class="dp-input" />
            </div>
            <div class="dp-field">
              <span class="dp-field__label">End</span>
              <input type="datetime-local" :value="isoToDatetimeLocal(taskEvent.end_time)"
                     @change="onCalendarEndChange" class="dp-input" />
            </div>
            <div class="dp-field">
              <span class="dp-field__label">Color</span>
              <div style="display:flex; align-items:center; gap:8px;">
                <input type="color" data-testid="event-color-input" :value="displayColor"
                       style="width:32px;height:28px;cursor:pointer;border:1px solid var(--border-1);border-radius:3px;background:transparent;"
                       @input="onColorInput" @change="onColorChange" />
                <button v-if="taskEvent.color || pendingColorValue != null"
                        data-testid="event-color-reset"
                        style="font-size:11px;color:var(--fg-5);cursor:pointer;background:none;border:none;"
                        @click="onColorReset">Reset</button>
              </div>
            </div>
            <RecurrencePicker :model-value="taskEvent.rrule" :start-time="taskEvent.start_time"
                              @update:model-value="onRecurrenceChange" />
            <RecurrenceEditDialog :visible="showColorScopeDialog" mode="event" action="edit"
                                  @confirm="onColorScopeConfirm" @cancel="onColorScopeCancel" />
          </div>
        </section>
      </template>

      <!-- ── Full task ─────────────────────────────────────────────────────── -->
      <template v-else>

        <!-- Motif -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Motif</span>
          </header>
          <div class="dp-section__body" data-testid="task-motif-picker">
            <MotifPicker
              :model-value="(task.motif as MotifSlot | null | undefined) ?? null"
              @update:model-value="onMotifChange" />
          </div>
        </section>

        <!-- Status -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Status</span>
          </header>
          <div class="dp-section__body">
            <select :value="task.status" @change="onStatusChange" class="dp-select">
              <option value="pending">Pending</option>
              <option value="in_progress">In Progress</option>
              <option value="done">Done</option>
              <option value="skipped">Skipped</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
        </section>

        <!-- Calendar -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Calendar</span>
          </header>
          <div class="dp-section__body">
            <template v-if="taskEvent">
              <div class="dp-field">
                <span class="dp-field__label">Start</span>
                <input type="datetime-local" :value="isoToDatetimeLocal(taskEvent.start_time)"
                       @change="onCalendarStartChange" class="dp-input" />
              </div>
              <div class="dp-field">
                <span class="dp-field__label">End</span>
                <input type="datetime-local" :value="isoToDatetimeLocal(taskEvent.end_time)"
                       @change="onCalendarEndChange" class="dp-input" />
              </div>
              <RecurrencePicker :model-value="taskEvent.rrule" :start-time="taskEvent.start_time"
                                @update:model-value="onRecurrenceChange" />
            </template>
            <template v-else-if="task?.anchor_id && !task?.start_time">
              <p class="dp-notes">Anchor task — drag to the calendar grid to schedule</p>
              <RecurrencePicker :model-value="task.rrule ?? null" :start-time="''"
                                @update:model-value="onAnchorRecurrenceChange" />
            </template>
            <template v-else>
              <p style="font-size:12px; color:var(--fg-5); margin:0;">Not on calendar — drag onto the time grid to schedule</p>
            </template>
          </div>
        </section>

        <!-- Location / Schedule -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Location</span>
          </header>
          <div class="dp-section__body">
            <template v-if="isBacklog">
              <p style="font-size:12px;color:var(--fg-5);margin:0 0 6px;">Unscheduled (backlog)</p>
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <input v-model="scheduleDate" type="date" class="dp-input" style="width:auto;" />
                <select v-model="scheduleAnchor" class="dp-select">
                  <option v-for="a in anchorStore.anchors" :key="a.id" :value="a.id">{{ a.name }}</option>
                </select>
                <button @click="scheduleTask" class="dp-btn" style="background:var(--accent-veil);color:var(--accent);border-color:var(--accent-soft);">Schedule</button>
              </div>
            </template>
            <template v-else>
              <div class="dp-field">
                <span class="dp-field__label">Date</span>
                <input
                  type="date"
                  data-testid="reschedule-date"
                  :value="taskPlanDate"
                  @change="onRescheduleDate"
                  class="dp-input"
                  style="width:auto;" />
              </div>
              <div class="dp-field">
                <span class="dp-field__label">Anchor</span>
                <select :value="anchorId" @change="moveToAnchor(($event.target as HTMLSelectElement).value)" class="dp-select">
                  <option v-for="a in anchorStore.anchors" :key="a.id" :value="a.id">{{ a.name }}</option>
                </select>
              </div>
              <button @click="moveToBacklog" class="dp-link" style="margin-top:4px;">Move to backlog</button>
            </template>
          </div>
        </section>

        <!-- Description -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Description</span>
          </header>
          <div class="dp-section__body">
            <textarea :value="task.description ?? ''" @blur="onDescBlur" rows="3"
                      placeholder="Add a description…" class="dp-textarea" />
          </div>
        </section>

        <!-- Subtasks -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Subtasks</span>
            <span class="dp-mono-faint">{{ subtasksDone }}/{{ subtasks.length }}</span>
          </header>
          <div class="dp-section__body">
            <ul class="t-rows">
              <li v-for="s in subtasks" :key="s.id" class="t-row" :data-motif="task.motif ?? 'anchor'">
                <label style="display:contents;cursor:pointer;">
                  <input type="checkbox" :checked="s.done" @change="updateSubtask(s.id, { done: !s.done })"
                         style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;" />
                  <span class="t-glyph" :data-status="s.done ? 'done' : 'todo'" />
                  <span :style="s.done ? 'text-decoration:line-through;color:var(--fg-6);' : 'color:var(--fg-2);'"
                        style="flex:1;font-size:12.5px;">{{ s.text }}</span>
                </label>
                <button @click="removeSubtask(s.id)"
                        style="color:var(--fg-6);font-size:11px;background:none;border:none;cursor:pointer;padding:0 4px;">✕</button>
              </li>
            </ul>
            <div style="display:flex;gap:8px;margin-top:4px;">
              <input v-model="newSubtaskText" @keydown.enter="addSubtask" placeholder="Add subtask…"
                     class="dp-input" style="flex:1;" />
              <button @click="addSubtask" class="dp-link">Add</button>
            </div>
          </div>
        </section>

        <!-- Links -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Links</span>
            <button @click="showAddLink = !showAddLink" class="dp-link">+ Add</button>
          </header>
          <div class="dp-section__body">
            <ul style="list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;">
              <li v-for="l in links" :key="l.id" style="display:flex;align-items:center;gap:8px;">
                <span style="flex-shrink:0;">{{ LINK_ICONS[l.category] ?? '📎' }}</span>
                <a :href="l.url" target="_blank" class="dp-link" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ l.label || l.url }}</a>
                <span style="font-size:10px;color:var(--fg-5);font-family:var(--font-mono);">{{ l.category }}</span>
                <button @click="removeLink(l.id)" style="color:var(--fg-6);font-size:11px;background:none;border:none;cursor:pointer;">✕</button>
              </li>
            </ul>
            <div v-if="showAddLink" style="display:flex;flex-direction:column;gap:6px;padding:10px;background:var(--bg-elev-2);border-radius:3px;border:1px solid var(--border-soft);">
              <input v-model="newLinkUrl" placeholder="URL" class="dp-input" />
              <input v-model="newLinkLabel" placeholder="Label (optional)" class="dp-input" />
              <select v-model="newLinkCategory" class="dp-select">
                <option value="document">Document</option>
                <option value="meeting">Meeting</option>
                <option value="pr">PR</option>
                <option value="issue">Issue</option>
                <option value="other">Other</option>
              </select>
              <div style="display:flex;gap:8px;justify-content:flex-end;">
                <button @click="showAddLink = false" class="dp-link">Cancel</button>
                <button @click="addLink" class="dp-btn" style="background:var(--bg-elev-3);color:var(--fg-2);border-color:var(--border-1);">Add</button>
              </div>
            </div>
          </div>
        </section>

        <!-- Dependencies -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Dependencies</span>
          </header>
          <div class="dp-section__body">
            <div class="dp-deps">
              <div class="dp-deps__group">
                <span class="dp-deps__lbl">Blocked by</span>
                <span v-if="!deps.blocked_by.length" class="dp-deps__none">—</span>
                <button v-for="d in deps.blocked_by" :key="d.id"
                        @click="openDep(d.type, d.entity_id)"
                        style="background:none;border:none;cursor:pointer;padding:0;">
                  <span class="t-chip" :data-motif="d.type === 'milestone' ? 'launch' : 'quiet'">
                    {{ d.name || depLabel(d.type, d.entity_id) }}
                    <button @click.stop="removeDep(d.id)" style="color:var(--fg-6);background:none;border:none;cursor:pointer;font-size:10px;margin-left:2px;">✕</button>
                  </span>
                </button>
              </div>
              <div class="dp-deps__group">
                <span class="dp-deps__lbl">Blocks</span>
                <span v-if="!deps.blocks.length" class="dp-deps__none">—</span>
                <button v-for="d in deps.blocks" :key="d.id"
                        @click="openDep(d.type, d.entity_id)"
                        style="background:none;border:none;cursor:pointer;padding:0;">
                  <span class="t-chip" :data-motif="d.type === 'milestone' ? 'launch' : 'quiet'">
                    {{ d.name || depLabel(d.type, d.entity_id) }}
                    <button @click.stop="removeDep(d.id)" style="color:var(--fg-6);background:none;border:none;cursor:pointer;font-size:10px;margin-left:2px;">✕</button>
                  </span>
                </button>
              </div>
            </div>
            <SearchAutocomplete :search-fn="searchForDependency" placeholder="Search tasks/milestones…" @select="addDependencyFromSearch" />
          </div>
        </section>

        <!-- Milestones -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Milestones</span>
          </header>
          <div class="dp-section__body">
            <span v-if="!(milestoneStore.taskMilestones[taskId] ?? []).length" style="font-size:12px;color:var(--fg-5);">None</span>
            <button v-for="m in (milestoneStore.taskMilestones[taskId] ?? [])" :key="m.id"
                    @click="openMilestone(m.id)"
                    style="display:flex;align-items:center;gap:8px;background:none;border:none;cursor:pointer;padding:3px 0;text-align:left;">
              <span v-if="m.color" style="width:8px;height:8px;border-radius:50%;flex-shrink:0;" :style="{ background: m.color }" />
              <span style="font-size:12.5px;" :style="m.color ? { color: m.color } : { color: 'var(--fg-2)' }">{{ m.name }}</span>
              <span style="font-size:10px;font-family:var(--font-mono);color:var(--fg-5);">{{ m.status }}</span>
            </button>
            <SearchAutocomplete :search-fn="searchForMilestone" placeholder="Search milestones…" @select="linkMilestoneFromSearch" />
          </div>
        </section>

        <!-- Context entries -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Context</span>
          </header>
          <div class="dp-section__body">
            <span v-if="!contexts.length" style="font-size:12px;color:var(--fg-5);">None</span>
            <div v-for="subject in contexts" :key="subject"
                 style="display:flex;align-items:center;justify-content:space-between;font-size:12.5px;">
              <router-link :to="'/context'" class="dp-link" style="font-size:inherit;">{{ subject }}</router-link>
              <button @click="unlinkContext(subject)" style="color:var(--fg-6);background:none;border:none;cursor:pointer;font-size:11px;">✕</button>
            </div>
            <SearchAutocomplete :search-fn="searchForContext" placeholder="Link context entry…" @select="linkContextFromSearch" />
          </div>
        </section>

        <!-- Follow-up config -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Follow-up</span>
            <button @click="showFollowup = !showFollowup" class="dp-link">{{ showFollowup ? 'Hide' : 'Edit' }}</button>
          </header>
          <div class="dp-section__body">
            <p v-if="task.followup_config && !showFollowup" style="font-size:12px;color:var(--fg-4);margin:0;">
              {{ task.followup_config.enabled ? `Enabled — pre every ${task.followup_config.pre_ack_interval_min}m` : 'Disabled (override)' }}
            </p>
            <p v-else-if="!task.followup_config && !showFollowup" style="font-size:12px;color:var(--fg-6);margin:0;font-style:italic;">Using anchor default</p>
            <div v-if="showFollowup" style="display:flex;flex-direction:column;gap:8px;padding:10px;background:var(--bg-elev-2);border-radius:3px;border:1px solid var(--border-soft);">
              <label style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--fg-3);">
                <input type="checkbox" :checked="task.followup_config?.enabled ?? false"
                       @change="(e) => toggleFollowup((e.target as HTMLInputElement).checked)" />
                Override anchor follow-up
              </label>
              <template v-if="task.followup_config?.enabled">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                  <label style="font-size:11px;color:var(--fg-5);display:flex;flex-direction:column;gap:3px;">
                    Pre interval (min)
                    <input :value="task.followup_config.pre_ack_interval_min" type="number" min="1" class="dp-input"
                           @change="patchFollowup({ pre_ack_interval_min: +($event.target as HTMLInputElement).value })" style="width:64px;" />
                  </label>
                  <label style="font-size:11px;color:var(--fg-5);display:flex;flex-direction:column;gap:3px;">
                    Max pings
                    <input :value="task.followup_config.pre_ack_max_pings" type="number" min="1" class="dp-input"
                           @change="patchFollowup({ pre_ack_max_pings: +($event.target as HTMLInputElement).value })" style="width:64px;" />
                  </label>
                  <label style="font-size:11px;color:var(--fg-5);display:flex;flex-direction:column;gap:3px;">
                    Post interval (min)
                    <input :value="task.followup_config.post_ack_interval_min" type="number" min="1" class="dp-input"
                           @change="patchFollowup({ post_ack_interval_min: +($event.target as HTMLInputElement).value })" style="width:64px;" />
                  </label>
                  <label style="font-size:11px;color:var(--fg-5);display:flex;flex-direction:column;gap:3px;">
                    Post pings
                    <input :value="task.followup_config.post_ack_pings" type="number" min="1" class="dp-input"
                           @change="patchFollowup({ post_ack_pings: +($event.target as HTMLInputElement).value })" style="width:64px;" />
                  </label>
                </div>
              </template>
            </div>
          </div>
        </section>

        <!-- Scope dialogs (teleported to body by RecurrenceEditDialog internally) -->
        <RecurrenceEditDialog :visible="showAnchorScopeDialog" mode="task" action="edit"
                              @confirm="onAnchorScopeConfirm" @cancel="onAnchorScopeCancel" />
        <RecurrenceEditDialog :visible="showAnchorDeleteDialog" mode="task" action="delete"
                              @confirm="onAnchorDeleteConfirm" @cancel="onAnchorDeleteCancel" />

      </template>
    </div>

    <!-- ── Footer ─────────────────────────────────────────────────────────── -->
    <footer class="dp-footer">
      <template v-if="task">
        <button
          v-if="task?.anchor_id && !task?.start_time"
          data-testid="delete-task-btn"
          class="dp-btn dp-btn--ghost-danger"
          @click="onDeleteAnchorTask">Delete</button>
        <button
          v-else
          data-testid="delete-task-btn"
          class="dp-btn dp-btn--ghost-danger"
          @click="deleteTask">Delete</button>
      </template>
      <button v-else-if="taskEvent" class="dp-btn dp-btn--ghost-danger" @click="deleteTask">Delete</button>
      <span v-else />
      <span class="dp-footer__hint"><kbd>⌘</kbd><kbd>⌫</kbd></span>
    </footer>

  </div>
</template>
