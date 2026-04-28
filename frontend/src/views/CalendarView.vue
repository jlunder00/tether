<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAnchorStore } from '../stores/anchors'
import { useEventStore } from '../stores/events'
import { usePlanStore } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import { useKanbanStore } from '../stores/kanban'
import { useContextStore } from '../stores/context'
import { useCalendarFocus } from '../composables/useCalendarFocus'
import { useSlideOver } from '../composables/useSlideOver'
import CalendarEventBlock from '../components/CalendarEventBlock.vue'
import CalendarFilterPanel from '../components/CalendarFilterPanel.vue'
import RecurrenceEditDialog from '../components/RecurrenceEditDialog.vue'
import type { RecurrenceEditScope, PendingRecurrence } from '../types/recurrence'
import { resolveEventColor } from '../composables/useColorResolver'
import { computeOverlapLayout, type EventLayout } from '../composables/useOverlapLayout'
import type { CalendarEvent } from '../types/events'
import type { Anchor } from '../stores/anchors'

const anchorStore = useAnchorStore()
const eventStore = useEventStore()
const planStore = usePlanStore()
const milestoneStore = useMilestoneStore()
const kanbanStore = useKanbanStore()
const contextStore = useContextStore()
const { focusedDay, setFocusedDay } = useCalendarFocus()
const { push: pushPanel } = useSlideOver()

// ─── View state ───────────────────────────────────────────────
const anchorPanelOpen = ref(true)
const sidebarWidth = ref(224) // px; matches w-56 default
const MIN_SIDEBAR = 160
const MAX_SIDEBAR = 480

// ─── View mode ────────────────────────────────────────────────
type ViewMode = 'week' | 'month'
const viewMode = ref<ViewMode>('week')

// ─── Sidebar resize ───────────────────────────────────────────
let resizing = false
let resizeStartX = 0
let resizeStartWidth = 0

function onResizeHandleMousedown(e: MouseEvent) {
  resizing = true
  resizeStartX = e.clientX
  resizeStartWidth = sidebarWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// ─── Event drag-to-reposition (mouse) ─────────────────────────
interface DragState {
  eventId: string
  originalStart: string
  originalEnd: string
  currentTop: number
  currentDayIndex: number
  columnRect: DOMRect | null
}
const draggingEvent = ref<DragState | null>(null)

const pendingRecurrence = ref<PendingRecurrence>(null)

const recurrenceDialogMode = computed<'event' | 'task'>(() => {
  const p = pendingRecurrence.value
  if (!p) return 'event'
  return p.kind.startsWith('task') ? 'task' : 'event'
})

const recurrenceDialogAction = computed<'edit' | 'delete' | 'move'>(() => {
  const p = pendingRecurrence.value
  if (!p) return 'edit'
  if (p.kind.endsWith('delete')) return 'delete'
  if (p.kind.endsWith('move')) return 'move'
  return 'edit'
})

async function onRecurrenceScopeConfirm(scope: RecurrenceEditScope) {
  const pending = pendingRecurrence.value
  pendingRecurrence.value = null
  if (!pending) return

  if (pending.kind === 'event-move') {
    await eventStore.moveEvent(pending.eventId, pending.startTime, pending.endTime, scope, pending.originalStartTime)
  } else if (pending.kind === 'event-edit') {
    // Apply patch with scope — PATCH /api/events/:id
    try {
      await fetch(`/api/events/${pending.eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...pending.patch, scope, original_start_time: pending.patch.original_start_time }),
      })
    } catch { /* ignore */ }
  } else if (pending.kind === 'event-delete') {
    await eventStore.deleteEvent(pending.eventId, scope, pending.originalStartTime)
  } else if (pending.kind === 'task-edit' || pending.kind === 'task-move' || pending.kind === 'task-delete') {
    // TODO: wire recurring task scope API when repeating tasks backend ships
  }
}

function onRecurrenceScopeCancel() {
  pendingRecurrence.value = null
}

// Distinguish click-as-open from click-and-drag-to-move. A bare click triggers
// mousedown→mouseup with no movement; without a threshold, mouseup commits a
// no-op move that still PATCHes the event (and triggers a backend round-trip).
const DRAG_THRESHOLD_PX = 5
let dragStartX = 0
let dragStartY = 0
let dragIntentConfirmed = false

function onEventMousedown(e: MouseEvent, event: CalendarEvent) {
  e.stopPropagation()
  const colEl = (e.target as HTMLElement).closest('[data-day-col]') as HTMLElement | null
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragIntentConfirmed = false
  draggingEvent.value = {
    eventId: event.id,
    originalStart: event.start_time,
    originalEnd: event.end_time,
    currentTop: eventTopPx(event),
    currentDayIndex: dayKeys.value.indexOf(event.start_time.slice(0, 10)),
    columnRect: colEl?.getBoundingClientRect() ?? null,
  }
  document.body.style.userSelect = 'none'
}

// ─── Drag-to-create on time grid (mouse) ──────────────────────
interface CreateState {
  dayKey: string
  startY: number
  currentY: number
  columnRect: DOMRect
}
const creatingEvent = ref<CreateState | null>(null)

function onDayColumnMousedown(e: MouseEvent, dayKey: string) {
  // Only start creation if click is directly on the column (not on an event block)
  if ((e.target as HTMLElement).closest('[data-event-block]')) return
  const col = e.currentTarget as HTMLElement
  const rect = col.getBoundingClientRect()
  const relY = e.clientY - rect.top
  creatingEvent.value = { dayKey, startY: relY, currentY: relY, columnRect: rect }
  document.body.style.userSelect = 'none'
}

// ─── Unified window mouse handlers ────────────────────────────
function onWindowMousemove(e: MouseEvent) {
  if (resizing) {
    const delta = e.clientX - resizeStartX
    sidebarWidth.value = Math.min(MAX_SIDEBAR, Math.max(MIN_SIDEBAR, resizeStartWidth + delta))
    return
  }
  if (draggingEvent.value) {
    if (!dragIntentConfirmed) {
      const dx = e.clientX - dragStartX
      const dy = e.clientY - dragStartY
      if (Math.sqrt(dx * dx + dy * dy) < DRAG_THRESHOLD_PX) return
      dragIntentConfirmed = true
    }
    // Update ghost position — track cursor Y relative to column
    if (draggingEvent.value.columnRect) {
      draggingEvent.value.currentTop = e.clientY - draggingEvent.value.columnRect.top
    }
    return
  }
  if (creatingEvent.value) {
    const relY = e.clientY - creatingEvent.value.columnRect.top
    creatingEvent.value.currentY = relY
    return
  }
}

async function onWindowMouseup(e: MouseEvent) {
  if (resizing) {
    resizing = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    return
  }

  if (draggingEvent.value) {
    const state = draggingEvent.value
    const wasConfirmedDrag = dragIntentConfirmed
    draggingEvent.value = null
    dragIntentConfirmed = false
    document.body.style.userSelect = ''

    // Click without drag — bail. The block's own @click handler opens the
    // event panel. Without this guard, a plain click commits a no-op move
    // that still fires a PATCH.
    if (!wasConfirmedDrag) return

    // Find which day column the mouse is over
    const el = document.elementFromPoint(e.clientX, e.clientY)
    const colEl = el?.closest('[data-day-col]') as HTMLElement | null

    if (!colEl) {
      // Dropped outside grid — snap back (no-op, original is already in store)
      return
    }

    const rect = colEl.getBoundingClientRect()
    const relY = Math.max(0, e.clientY - rect.top)
    const snapY = snapToMinutes(relY, 15)
    const hour = Math.floor(snapY / HOUR_HEIGHT) + START_HOUR
    const minute = Math.round(((snapY % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15

    const dayStr = colEl.getAttribute('data-day-col')!
    const existing = eventStore.events.find(ev => ev.id === state.eventId)
    if (!existing) return

    const durationMs = new Date(existing.end_time).getTime() - new Date(existing.start_time).getTime()
    const newStart = new Date(dayStr + 'T00:00:00')
    newStart.setHours(hour, minute, 0, 0)
    const newEnd = new Date(newStart.getTime() + durationMs)

    // Recurring occurrence — defer commit until the user picks an edit scope.
    // Backend (PR #219) requires {scope, original_start_time} to know whether
    // to EXDATE this instance, split the series, or move the master.
    if (existing.is_occurrence) {
      pendingRecurrence.value = {
        kind: 'event-move',
        eventId: state.eventId,
        startTime: newStart.toISOString(),
        endTime: newEnd.toISOString(),
        originalStartTime: state.originalStart,
      }
      return
    }

    await eventStore.moveEvent(state.eventId, newStart.toISOString(), newEnd.toISOString())
    return
  }

  if (creatingEvent.value) {
    const state = creatingEvent.value
    creatingEvent.value = null
    document.body.style.userSelect = ''

    const minY = Math.min(state.startY, state.currentY)
    const maxY = Math.max(state.startY, state.currentY)
    const heightY = maxY - minY

    // Minimum 15 minutes drag
    const MIN_HEIGHT = (15 / 60) * HOUR_HEIGHT
    if (heightY < MIN_HEIGHT) return

    const startSnapped = snapToMinutes(minY, 15)
    const endSnapped = snapToMinutes(maxY, 15)

    const startHour = Math.floor(startSnapped / HOUR_HEIGHT) + START_HOUR
    const startMin = Math.round(((startSnapped % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15
    const endHour = Math.floor(endSnapped / HOUR_HEIGHT) + START_HOUR
    const endMin = Math.round(((endSnapped % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15

    const startDate = new Date(state.dayKey + 'T00:00:00')
    startDate.setHours(startHour, startMin, 0, 0)
    const endDate = new Date(state.dayKey + 'T00:00:00')
    endDate.setHours(endHour, endMin, 0, 0)

    const taskId = await eventStore.createTaskAndPromote(startDate.toISOString(), endDate.toISOString())
    if (taskId) {
      pushPanel({ kind: 'task', entityId: taskId })
    }
    return
  }
}

function snapToMinutes(y: number, intervalMin: number): number {
  const minutesPerPx = 60 / HOUR_HEIGHT
  const totalMinutes = y * minutesPerPx
  const snapped = Math.round(totalMinutes / intervalMin) * intervalMin
  return (snapped / 60) * HOUR_HEIGHT
}

onMounted(() => {
  window.addEventListener('mousemove', onWindowMousemove)
  window.addEventListener('mouseup', onWindowMouseup)
  anchorStore.fetchAnchors()
  planStore.fetchPlan(focusedDay.value)
  milestoneStore.fetchAll()
  kanbanStore.fetchColumns()
  contextStore.fetchRootNodes().catch(() => {})
  document.addEventListener('click', onDocumentClick)
  document.addEventListener('keydown', onDocumentKeydown)
  loadEvents()
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onWindowMousemove)
  window.removeEventListener('mouseup', onWindowMouseup)
  document.removeEventListener('click', onDocumentClick)
  document.removeEventListener('keydown', onDocumentKeydown)
})

// ─── Week date range ──────────────────────────────────────────
function localDateString(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function getWeekStart(d: Date): Date {
  const result = new Date(d)
  result.setDate(result.getDate() - result.getDay()) // Sunday start
  return result
}

const today = localDateString(new Date())
const weekStart = ref(getWeekStart(new Date()))

// Month view navigation
const monthViewDate = ref(new Date())

const days = computed<Date[]>(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    return d
  }),
)

// Cached keys so we don't recompute localDateString for every cell on every render.
const dayKeys = computed(() => days.value.map(localDateString))

function navigatePrev() {
  if (viewMode.value === 'month') {
    const d = new Date(monthViewDate.value)
    d.setMonth(d.getMonth() - 1)
    monthViewDate.value = d
  } else {
    shiftWeek(-7)
  }
}

function navigateNext() {
  if (viewMode.value === 'month') {
    const d = new Date(monthViewDate.value)
    d.setMonth(d.getMonth() + 1)
    monthViewDate.value = d
  } else {
    shiftWeek(7)
  }
}

function shiftWeek(deltaDays: number) {
  const d = new Date(weekStart.value)
  d.setDate(d.getDate() + deltaDays)
  weekStart.value = d
  loadEvents()
}

function goToday() {
  weekStart.value = getWeekStart(new Date())
  if (viewMode.value === 'month') monthViewDate.value = new Date()
  loadEvents()
}

// ─── Month grid ───────────────────────────────────────────────
const monthLabel = computed(() =>
  monthViewDate.value.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
)

const weekLabel = computed(() => {
  return `${days.value[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${days.value[6].toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`
})

const monthCalendarDates = computed<string[]>(() => {
  const y = monthViewDate.value.getFullYear()
  const m = monthViewDate.value.getMonth()
  const first = new Date(y, m, 1)
  // Sunday start: offset is first.getDay() (0=Sun, 1=Mon, ...)
  const startOffset = first.getDay()
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(y, m, 1 - startOffset + i)
    return localDateString(d)
  })
})

const currentMonthIndex = computed(() => monthViewDate.value.getMonth())

function isCurrentMonth(date: string) {
  return new Date(date + 'T12:00:00').getMonth() === currentMonthIndex.value
}

function eventsForDay(dayKey: string): CalendarEvent[] {
  return filteredEventsByDay.value[dayKey] ?? []
}

function clickMonthDay(dayKey: string) {
  focusDay(dayKey)
  // Set weekStart so that the week view lands on the week containing this day
  weekStart.value = getWeekStart(new Date(dayKey + 'T12:00:00'))
  viewMode.value = 'week'
  loadEvents()
}

// ─── Day focus ────────────────────────────────────────────────
function focusDay(dayKey: string) {
  setFocusedDay(dayKey)
  planStore.fetchPlan(dayKey)
}

// ─── Hours displayed in grid ──────────────────────────────────
const HOUR_HEIGHT = 60 // px per hour
const START_HOUR = 0
const END_HOUR = 24

const hours = Array.from({ length: END_HOUR - START_HOUR }, (_, i) => START_HOUR + i)

// ─── Filter state ─────────────────────────────────────────────
const filterOpen = ref(false)
interface CalendarFilter {
  contextNodeIds: Set<string>
  anchorIds: Set<string>
  kanbanColumnIds: Set<string>
}
const emptyFilter = (): CalendarFilter => ({
  contextNodeIds: new Set(),
  anchorIds: new Set(),
  kanbanColumnIds: new Set(),
})
const activeFilter = ref<CalendarFilter>(emptyFilter())
const activeFilterCount = computed(() =>
  activeFilter.value.contextNodeIds.size + activeFilter.value.anchorIds.size + activeFilter.value.kanbanColumnIds.size
)

// Expand a set of context node ids into the union of their subtrees (over the
// nodes already loaded in the store). Selecting a parent should match events
// tagged with any descendant.
function expandSubtree(ids: Set<string>): Set<string> {
  const result = new Set<string>(ids)
  const stack = [...ids]
  const allNodes = Object.values(contextStore.nodes)
  while (stack.length) {
    const id = stack.pop()!
    for (const n of allNodes) {
      if (n.parent_id === id && !result.has(n.id)) {
        result.add(n.id)
        stack.push(n.id)
      }
    }
  }
  return result
}

// Anchors define disjoint daily time windows; an event "belongs to" the latest
// anchor whose time is ≤ the event's local time. Returns the anchor id or null.
function anchorForEventTime(ev: CalendarEvent): string | null {
  if (!anchorStore.anchors.length) return null
  const d = new Date(ev.start_time)
  const evMin = d.getHours() * 60 + d.getMinutes()
  const sorted = [...anchorStore.anchors].sort((a, b) => a.time.localeCompare(b.time))
  let active: Anchor | null = null
  for (const a of sorted) {
    const [h, m] = a.time.split(':').map(Number)
    const aMin = (h || 0) * 60 + (m || 0)
    if (aMin <= evMin) active = a
    else break
  }
  return active?.id ?? null
}

// Tasks allowed by context/milestone filter (null = no context filter active)
const allowedTaskIds = computed<Set<string> | null>(() => {
  const { contextNodeIds } = activeFilter.value
  if (contextNodeIds.size === 0) return null
  const ids = new Set<string>()
  const expandedNodeIds = expandSubtree(contextNodeIds)

  // Milestone nodes (node_type === 'milestone') own task_ids directly via the
  // milestone store; selecting them should pull in those tasks.
  for (const m of milestoneStore.all) {
    if (expandedNodeIds.has(m.id)) for (const tid of m.task_ids) ids.add(tid)
  }

  // Context nodes match events by context_subject (name). Duplicate-named nodes
  // merge filter behavior — predictable rather than silently dropping one.
  const allowedNames = new Set<string>()
  for (const node of Object.values(contextStore.nodes)) {
    if (expandedNodeIds.has(node.id)) allowedNames.add(node.name)
  }
  for (const ev of eventStore.events) {
    if (ev.context_subject && allowedNames.has(ev.context_subject) && ev.task_id) {
      ids.add(ev.task_id)
    }
  }
  return ids
})

// ─── Click-away to close filter ───────────────────────────────
function onDocumentClick(e: MouseEvent) {
  if (!filterOpen.value) return
  const panel = document.getElementById('calendar-filter-panel')
  const button = document.getElementById('calendar-filter-button')
  if (!panel?.contains(e.target as Node) && !button?.contains(e.target as Node)) {
    filterOpen.value = false
  }
}

// Escape closes the filter regardless of focus (the panel's own keydown
// handler only fires when the panel is focused, which it isn't on open).
function onDocumentKeydown(e: KeyboardEvent) {
  if (filterOpen.value && e.key === 'Escape') filterOpen.value = false
}

// ─── Events mapped per day (with filter) ─────────────────────
const filteredEventsByDay = computed(() => {
  const allowed = allowedTaskIds.value
  const { anchorIds } = activeFilter.value
  const map: Record<string, CalendarEvent[]> = {}
  for (const ev of eventStore.events) {
    const dayKey = ev.start_time.slice(0, 10)
    if (!map[dayKey]) map[dayKey] = []

    // Context/milestone filter
    if (allowed !== null) {
      if (ev.task_id === null || !allowed.has(ev.task_id)) continue
    }

    // Anchor filter: map event's local start time to an anchor; skip if not in selected set
    if (anchorIds.size > 0) {
      const resolvedAnchor = anchorForEventTime(ev)
      if (resolvedAnchor === null || !anchorIds.has(resolvedAnchor)) continue
    }

    // Kanban filter: match via task_id → column not yet available without a task→column index.
    // The kanban store tracks columns but not task↔column assignments directly.
    // Skipping kanban filter here until a task→column index is exposed.
    // TODO: wire kanban column filter once task store exposes column_id

    map[dayKey].push(ev)
  }
  return map
})

// For the week view: only timed (non-all-day) events per day
const eventsByDay = computed(() => {
  const map: Record<string, CalendarEvent[]> = {}
  for (const key of dayKeys.value) {
    map[key] = (filteredEventsByDay.value[key] ?? []).filter(ev => !ev.is_all_day)
  }
  return map
})

// All-day events per day (rendered in the band above the timed grid)
const allDayEventsByDay = computed(() => {
  const map: Record<string, CalendarEvent[]> = {}
  for (const key of dayKeys.value) {
    map[key] = (filteredEventsByDay.value[key] ?? []).filter(ev => ev.is_all_day)
  }
  return map
})

// Sidebar tasks filtered by selected milestones
const filteredAnchorsWithTasks = computed(() => {
  const allowed = allowedTaskIds.value
  const plan = planStore.plans[focusedDay.value] ?? planStore.plan
  if (!plan) return []
  return anchorStore.anchors.map((a: Anchor) => {
    const tasks = plan.anchors[a.id]?.tasks ?? []
    const filtered = allowed === null ? tasks : tasks.filter(t => allowed.has(t.id))
    return { anchor: a, tasks: filtered }
  })
})

function eventTopPx(event: CalendarEvent): number {
  const d = new Date(event.start_time)
  return (d.getHours() + d.getMinutes() / 60 - START_HOUR) * HOUR_HEIGHT
}

function eventHeightPx(event: CalendarEvent): number {
  const start = new Date(event.start_time).getTime()
  const end = new Date(event.end_time).getTime()
  const minutes = (end - start) / 60_000
  return Math.max((minutes / 60) * HOUR_HEIGHT, 20)
}

function resolveColor(event: CalendarEvent): string {
  return resolveEventColor(event, milestoneStore.all, contextStore.nodes)
}

// ─── Overlap layout per day ───────────────────────────────────
const overlapLayouts = computed<Record<string, Record<string, EventLayout>>>(() => {
  const byDay: Record<string, Record<string, EventLayout>> = {}
  for (const [dayKey, evs] of Object.entries(eventsByDay.value)) {
    byDay[dayKey] = computeOverlapLayout(evs)
  }
  return byDay
})

// Creation drag selection rect (in px relative to day column)
const createSelectionStyle = computed(() => {
  if (!creatingEvent.value) return null
  const minY = Math.min(creatingEvent.value.startY, creatingEvent.value.currentY)
  const maxY = Math.max(creatingEvent.value.startY, creatingEvent.value.currentY)
  return { top: `${minY}px`, height: `${maxY - minY}px` }
})

// ─── Anchor panel: tasks for focused day (unfiltered, sidebar uses its own filter) ──
const anchorsWithTasks = computed(() => {
  const plan = planStore.plans[focusedDay.value] ?? planStore.plan
  if (!plan) return []
  return anchorStore.anchors.map((a: Anchor) => ({
    anchor: a,
    tasks: plan.anchors[a.id]?.tasks ?? [],
  }))
})

// ─── Drag-to-promote: task → event (HTML5 DnD — sidebar to calendar) ────────────
const dragOverDay = ref<string | null>(null)
const dragOverHour = ref<number | null>(null)

function onDragOver(e: DragEvent, day: Date) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  dragOverDay.value = localDateString(day)
  if (e.currentTarget instanceof HTMLElement) {
    const rect = e.currentTarget.getBoundingClientRect()
    const relY = e.clientY - rect.top
    dragOverHour.value = Math.floor(relY / HOUR_HEIGHT) + START_HOUR
  }
}

function onDragLeave() {
  dragOverDay.value = null
  dragOverHour.value = null
}

async function onDrop(e: DragEvent, day: Date) {
  e.preventDefault()
  dragOverDay.value = null
  dragOverHour.value = null

  const raw = e.dataTransfer?.getData('text/plain')
  if (!raw || !(e.currentTarget instanceof HTMLElement)) return

  let payload: { taskId?: string }
  try { payload = JSON.parse(raw) } catch { return }

  // Only handle task→event promotions here (eventId moves handled by mouse drag)
  if (!payload.taskId) return

  // Map drop position to a quarter-hour slot.
  const rect = e.currentTarget.getBoundingClientRect()
  const relY = e.clientY - rect.top
  const hour = Math.floor(relY / HOUR_HEIGHT) + START_HOUR
  const minute = Math.round(((relY % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15
  const startDate = new Date(day)
  startDate.setHours(hour, minute, 0, 0)

  // If the dragged task already has a calendar event, move it instead of
  // promoting again — promoting creates a duplicate event row.
  const existingEvent = eventStore.events.find(ev => ev.task_id === payload.taskId)
  if (existingEvent) {
    const durationMs = new Date(existingEvent.end_time).getTime() - new Date(existingEvent.start_time).getTime()
    const endDate = new Date(startDate.getTime() + durationMs)
    await eventStore.moveEvent(existingEvent.id, startDate.toISOString(), endDate.toISOString())
    return
  }

  // Promoting a sidebar task (not yet on calendar) to an event.
  let title = 'Task'
  for (const anchorPlan of Object.values(planStore.plan?.anchors ?? {})) {
    const found = anchorPlan.tasks.find(t => t.id === payload.taskId)
    if (found) { title = found.text; break }
  }
  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000) // 1 hour default
  await eventStore.promoteTask(payload.taskId!, startDate.toISOString(), endDate.toISOString(), title)
}

// ─── Panel navigation ─────────────────────────────────────────
function openEventPanel(event: CalendarEvent) {
  // Promoted tasks: open the source task detail so the user can edit it.
  // Standalone events: open via kind:'event' (wired to TaskDetailPanel by SlideOverStack).
  if (event.task_id) {
    pushPanel({ kind: 'task', entityId: event.task_id })
  } else {
    pushPanel({ kind: 'event', entityId: event.id })
  }
}

// ─── Data loading ──────────────────────────────────────────────
function loadEvents() {
  eventStore.fetchEvents(dayKeys.value[0], dayKeys.value[6])
}

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
</script>

<template>
  <div class="flex h-full bg-gray-900 text-white overflow-hidden">

    <!-- ── Anchor / Side Panel ── -->
    <aside
      data-testid="anchor-panel"
      class="flex-shrink-0 border-r border-white/10 flex flex-col transition-all duration-200 relative"
      :style="anchorPanelOpen ? { width: sidebarWidth + 'px' } : { width: '40px' }"
    >
      <!-- Toggle button -->
      <button
        data-testid="anchor-panel-toggle"
        class="flex items-center justify-center h-10 w-full border-b border-white/10 hover:bg-white/10 transition-colors text-white/50 hover:text-white flex-shrink-0"
        :title="anchorPanelOpen ? 'Collapse panel' : 'Expand panel'"
        @click="anchorPanelOpen = !anchorPanelOpen"
      >
        <svg class="w-4 h-4 transition-transform" :class="anchorPanelOpen ? '' : 'rotate-180'" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>

      <!-- Panel content — block layout so anchor blocks size to content and the panel scrolls -->
      <div
        v-if="anchorPanelOpen"
        data-testid="anchor-panel-content"
        class="flex-1 overflow-y-auto p-2 space-y-2"
      >
        <!-- Focused day label -->
        <div class="text-xs text-white/40 uppercase tracking-wide px-1 pt-1 select-none">
          {{ new Date(focusedDay + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) }}
        </div>

        <!-- Anchor blocks with task lists -->
        <div
          v-for="{ anchor, tasks } in (activeFilterCount > 0 ? filteredAnchorsWithTasks : anchorsWithTasks)"
          :key="anchor.id"
          class="rounded-lg border border-white/5 overflow-hidden"
        >
          <!-- Anchor header -->
          <div class="flex items-center gap-1.5 px-2 py-1.5" :style="{ borderLeft: `3px solid ${anchor.color}` }">
            <span class="text-xs font-medium text-white/80 truncate flex-1">{{ anchor.name }}</span>
            <span class="text-[10px] text-white/30">{{ anchor.time }}</span>
          </div>
          <!-- Task list — max height + scroll so one long anchor doesn't consume the panel -->
          <ul class="flex flex-col gap-0.5 px-1 pb-1 max-h-36 overflow-y-auto">
            <li
              v-for="task in tasks"
              :key="task.id"
              draggable="true"
              class="text-xs px-1.5 py-1 rounded cursor-grab hover:bg-white/5 text-white/60 hover:text-white/90 transition-colors truncate"
              :class="task.status === 'done' ? 'line-through opacity-40' : ''"
              @click.stop="pushPanel({ kind: 'task', entityId: task.id })"
              @dragstart="(e: DragEvent) => {
                if (e.dataTransfer) {
                  e.dataTransfer.effectAllowed = 'copy'
                  e.dataTransfer.setData('text/plain', JSON.stringify({ taskId: task.id }))
                }
              }"
            >
              {{ task.text }}
            </li>
            <li v-if="!tasks.length" class="text-[11px] text-white/20 px-1.5 py-0.5">No tasks</li>
          </ul>
        </div>

        <div v-if="!anchorsWithTasks.length" class="text-xs text-white/30 px-1">No anchors</div>

        <div class="text-[10px] text-white/20 px-1 pt-2 select-none leading-tight">
          Drag tasks into the calendar to schedule them
        </div>
      </div>

      <!-- Resize handle — only visible when panel is open -->
      <div
        v-if="anchorPanelOpen"
        class="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-indigo-500/40 transition-colors z-10"
        @mousedown.prevent="onResizeHandleMousedown"
      />
    </aside>

    <!-- ── Calendar Grid ── -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">

      <!-- Toolbar -->
      <header class="flex items-center gap-3 px-4 py-2 border-b border-white/10 flex-shrink-0">
        <h1 class="text-lg font-bold">Calendar</h1>
        <div class="flex items-center gap-1 ml-2">
          <button @click="navigatePrev" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-sm transition-colors">‹</button>
          <button @click="goToday" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-xs transition-colors">Today</button>
          <button @click="navigateNext" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-sm transition-colors">›</button>
        </div>
        <span class="text-sm text-white/50">
          {{ viewMode === 'month' ? monthLabel : weekLabel }}
        </span>
        <!-- View mode toggle -->
        <button
          data-testid="view-mode-toggle"
          class="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-xs text-white/50 hover:text-white hover:bg-white/10 transition-colors border border-white/10"
          @click="viewMode = viewMode === 'week' ? 'month' : 'week'"
        >
          {{ viewMode === 'week' ? 'Month' : 'Week' }}
        </button>
        <!-- Filter button -->
        <div class="relative">
          <button
            id="calendar-filter-button"
            data-testid="filter-button"
            class="flex items-center gap-1 px-2 py-0.5 rounded text-xs border transition-colors"
            :class="activeFilterCount > 0
              ? 'text-indigo-300 border-indigo-500/40 bg-indigo-500/10 hover:bg-indigo-500/20'
              : 'text-white/50 border-white/10 hover:text-white hover:bg-white/10'"
            @click.stop="filterOpen = !filterOpen"
          >
            Filter
            <span v-if="activeFilterCount > 0" class="bg-indigo-500 text-white rounded-full text-[10px] px-1 leading-none py-0.5 font-bold">
              {{ activeFilterCount }}
            </span>
          </button>
          <Teleport to="body">
            <div
              v-if="filterOpen"
              id="calendar-filter-panel"
              class="fixed z-50"
              style="top: 56px; right: 16px"
              @click.stop
            >
              <CalendarFilterPanel
                v-model="activeFilter"
                :root-nodes="contextStore.rootNodes"
                :children-of="contextStore.childrenOf"
                :fetch-children="contextStore.fetchChildren"
                :anchors="anchorStore.anchors"
                :kanban-columns="kanbanStore.columns"
                @close="filterOpen = false"
              />
            </div>
          </Teleport>
        </div>
      </header>

      <!-- ── Month View ── -->
      <div v-if="viewMode === 'month'" data-testid="month-view" class="flex-1 overflow-y-auto p-3">
        <!-- Day-of-week headers (Sun start, matching week view) -->
        <div class="grid grid-cols-7 mb-1">
          <div
            v-for="label in DAY_LABELS"
            :key="label"
            class="text-center text-xs text-white/30 py-1"
          >
            {{ label }}
          </div>
        </div>
        <!-- Day cells -->
        <div class="grid grid-cols-7 gap-1">
          <div
            v-for="date in monthCalendarDates"
            :key="date"
            :data-testid="`month-day-${date}`"
            :data-day="date"
            class="min-h-[72px] rounded-lg p-1.5 cursor-pointer transition-colors"
            :class="[
              isCurrentMonth(date) ? 'bg-white/5 hover:bg-white/10' : 'bg-white/[0.02] opacity-40',
              date === today ? 'ring-1 ring-indigo-400/50' : '',
              date === focusedDay ? 'ring-1 ring-indigo-400' : '',
            ]"
            @click="clickMonthDay(date)"
          >
            <div class="text-xs font-medium mb-1"
                 :class="date === today ? 'text-indigo-400' : 'text-white/50'">
              {{ new Date(date + 'T12:00:00').getDate() }}
            </div>
            <!-- Event pills -->
            <div class="flex flex-col gap-0.5">
              <div
                v-for="ev in eventsForDay(date).slice(0, 3)"
                :key="ev.id"
                class="rounded text-[10px] px-1 py-0.5 truncate font-medium text-white leading-none"
                :style="{ backgroundColor: resolveColor(ev) }"
              >
                {{ ev.title }}
              </div>
              <div
                v-if="eventsForDay(date).length > 3"
                class="text-[10px] text-white/40 px-1"
              >
                +{{ eventsForDay(date).length - 3 }} more
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Week View ── -->
      <template v-if="viewMode === 'week'">
        <!-- Scrollable time grid — header lives inside so both share the same
             container width even when the scrollbar is visible. -->
        <div class="flex-1 overflow-y-auto" data-testid="calendar-grid">

          <!-- Day-of-week header — sticky inside scroll container so it always
               has the same width context as the day columns beneath it. -->
          <div class="sticky top-0 z-10 flex border-b border-white/10 bg-gray-900 pl-12">
            <div
              v-for="(day, i) in days"
              :key="dayKeys[i]"
              :data-testid="`day-header-${i}`"
              :data-day="dayKeys[i]"
              :data-focused="focusedDay === dayKeys[i] ? 'true' : undefined"
              class="flex-1 text-center py-1.5 text-xs cursor-pointer hover:bg-white/5 transition-colors select-none"
              :class="[
                dayKeys[i] === today ? 'text-indigo-400 font-semibold' : 'text-white/50',
                focusedDay === dayKeys[i] ? 'bg-indigo-500/10' : '',
              ]"
              @click="focusDay(dayKeys[i])"
            >
              {{ DAY_LABELS[day.getDay()] }} {{ day.getDate() }}
            </div>
          </div>

          <!-- All-day band — one row above the timed grid, one chip per is_all_day event -->
          <div data-testid="all-day-band" class="flex border-b border-white/10 bg-gray-900/80 pl-12">
            <div
              v-for="(_, i) in days"
              :key="dayKeys[i]"
              class="flex-1 min-h-[24px] flex flex-wrap gap-0.5 px-1 py-0.5 border-l border-white/5"
            >
              <div
                v-for="ev in allDayEventsByDay[dayKeys[i]]"
                :key="ev.id"
                class="rounded text-[10px] px-1 py-0.5 truncate font-medium text-white leading-none cursor-pointer"
                :style="{ backgroundColor: resolveColor(ev) }"
                data-event-block
                @click="openEventPanel(ev)"
                @mousedown.stop="(e: MouseEvent) => onEventMousedown(e, ev)"
              >
                {{ ev.title }}
              </div>
            </div>
          </div>

          <div data-testid="week-view" class="flex">

            <!-- Hour labels -->
            <div class="flex-shrink-0 w-12 select-none">
              <div
                v-for="h in hours"
                :key="h"
                class="border-b border-white/5 text-right pr-1 text-[10px] text-white/30"
                :style="{ height: `${HOUR_HEIGHT}px`, lineHeight: `${HOUR_HEIGHT}px` }"
              >
                {{ h === 0 ? '' : `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}` }}
              </div>
            </div>

            <!-- Day columns -->
            <div
              v-for="(day, i) in days"
              :key="dayKeys[i]"
              :data-testid="`day-col-${dayKeys[i]}`"
              :data-day-col="dayKeys[i]"
              class="flex-1 relative border-l border-white/5 min-w-0"
              :class="[
                dragOverDay === dayKeys[i] ? 'bg-indigo-500/10' : '',
                focusedDay === dayKeys[i] ? 'ring-1 ring-inset ring-indigo-400/30' : '',
              ]"
              :style="{ height: `${HOUR_HEIGHT * (END_HOUR - START_HOUR)}px` }"
              @click.self="focusDay(dayKeys[i])"
              @mousedown="(e: MouseEvent) => onDayColumnMousedown(e, dayKeys[i])"
              @dragover="(e: DragEvent) => onDragOver(e, day)"
              @dragleave="onDragLeave"
              @drop="(e: DragEvent) => onDrop(e, day)"
            >
              <!-- Hour grid lines -->
              <div
                v-for="h in hours"
                :key="h"
                class="absolute inset-x-0 border-b border-white/5"
                :style="{ top: `${(h - START_HOUR) * HOUR_HEIGHT}px`, height: `${HOUR_HEIGHT}px` }"
              />

              <!-- Today highlight -->
              <div
                v-if="dayKeys[i] === today"
                class="absolute inset-0 bg-indigo-500/5 pointer-events-none"
              />

              <!-- Focused day highlight (stronger than today) -->
              <div
                v-if="focusedDay === dayKeys[i]"
                class="absolute inset-0 bg-indigo-400/8 pointer-events-none"
              />

              <!-- Event blocks — using CalendarEventBlock component -->
              <CalendarEventBlock
                v-for="event in eventsByDay[dayKeys[i]]"
                :key="event.id"
                :event="event"
                :top-px="eventTopPx(event)"
                :height-px="eventHeightPx(event)"
                :left-percent="overlapLayouts[dayKeys[i]]?.[event.id]?.leftPercent ?? 0"
                :width-percent="overlapLayouts[dayKeys[i]]?.[event.id]?.widthPercent ?? 100"
                :resolved-color="resolveColor(event)"
                :style="draggingEvent?.eventId === event.id ? { opacity: 0.5 } : {}"
                data-event-block
                @click="openEventPanel(event)"
                @mousedown="(e: MouseEvent) => onEventMousedown(e, event)"
              />

              <!-- Creation drag selection rectangle -->
              <div
                v-if="creatingEvent?.dayKey === dayKeys[i] && createSelectionStyle"
                class="absolute inset-x-1 bg-blue-500/30 border border-blue-400 rounded pointer-events-none z-20"
                :style="createSelectionStyle"
              />

              <!-- Drop indicator (sidebar DnD) -->
              <div
                v-if="dragOverDay === dayKeys[i] && dragOverHour !== null"
                class="absolute inset-x-1 h-0.5 bg-indigo-400 rounded pointer-events-none z-20"
                :style="{ top: `${(dragOverHour! - START_HOUR) * HOUR_HEIGHT}px` }"
              />
            </div>
          </div>
        </div>
      </template>
    </div>

    <router-view />

    <RecurrenceEditDialog
      :visible="pendingRecurrence !== null"
      :mode="recurrenceDialogMode"
      :action="recurrenceDialogAction"
      @confirm="onRecurrenceScopeConfirm"
      @cancel="onRecurrenceScopeCancel"
    />
  </div>
</template>
