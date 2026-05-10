<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { localDateString } from '../lib/dateUtils'
import { useDragEdgeScroll } from '../composables/useDragEdgeScroll'
import { useAnchorStore } from '../stores/anchors'
import { useEventStore } from '../stores/events'
import { usePlanStore } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import { useKanbanStore } from '../stores/kanban'
import { useContextStore } from '../stores/context'
import { useCalendarFocus } from '../composables/useCalendarFocus'
import { useSlideOver } from '../composables/useSlideOver'
import TaskCard from '../components/TaskCard.vue'
import CalendarFilterPanel from '../components/CalendarFilterPanel.vue'
import RecurrenceEditDialog from '../components/RecurrenceEditDialog.vue'
import type { RecurrenceEditScope, PendingRecurrence } from '../types/recurrence'
import { resolveEventColor } from '../composables/useColorResolver'
import { textOnColor } from '../composables/useTextOnColor'
import { computeOverlapLayout, computeOverlapBands, type EventLayout, type OverlapBand } from '../composables/useOverlapLayout'
import type { CalendarEvent } from '../types/events'
import type { Anchor } from '../stores/anchors'
import type { Task } from '../stores/plan'

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
    await eventStore.patchEvent(
      pending.eventId,
      pending.patch,
      scope,
      pending.patch.original_start_time as string | undefined,
    )
  } else if (pending.kind === 'event-delete') {
    await eventStore.deleteEvent(pending.eventId, scope, pending.originalStartTime)
  } else if (pending.kind === 'task-edit' || pending.kind === 'task-move' || pending.kind === 'task-delete') {
    // TODO: wire recurring task scope API when repeating tasks backend ships
  }
}

function onRecurrenceScopeCancel() {
  pendingRecurrence.value = null
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
  if (creatingEvent.value) {
    const relY = e.clientY - creatingEvent.value.columnRect.top
    creatingEvent.value.currentY = relY
    return
  }
}

async function onWindowMouseup(_e: MouseEvent) {
  if (resizing) {
    resizing = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
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

/**
 * Detect all-day events including the Google Calendar pattern where the
 * backend sets is_all_day: false but sends UTC-midnight start times
 * (e.g. '2024-06-10T00:00:00Z' or '2024-06-10T00:00:00.000Z').
 *
 * Parses UTC time components instead of suffix-matching so it is robust
 * to fractional-second precision (T00:00:00.000Z) and ±00:00 variants.
 */
function isAllDay(ev: CalendarEvent): boolean {
  if (ev.is_all_day) return true
  const d = new Date(ev.start_time)
  return d.getUTCHours() === 0 && d.getUTCMinutes() === 0 && d.getUTCSeconds() === 0
}

// For the week view: only timed (non-all-day) events per day
const eventsByDay = computed(() => {
  const map: Record<string, CalendarEvent[]> = {}
  for (const key of dayKeys.value) {
    map[key] = (filteredEventsByDay.value[key] ?? []).filter(ev => !isAllDay(ev))
  }
  return map
})

// All-day events per day (rendered in the band above the timed grid)
const allDayEventsByDay = computed(() => {
  const map: Record<string, CalendarEvent[]> = {}
  for (const key of dayKeys.value) {
    map[key] = (filteredEventsByDay.value[key] ?? []).filter(ev => isAllDay(ev))
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

// ─── Overlap background bands per day ────────────────────────
// Helpers that match the signature expected by computeOverlapBands
function _topByTime(startTime: string): number {
  const d = new Date(startTime)
  return (d.getHours() + d.getMinutes() / 60 - START_HOUR) * HOUR_HEIGHT
}
function _heightByTime(startTime: string, endTime: string): number {
  const start = new Date(startTime).getTime()
  const end = new Date(endTime).getTime()
  const minutes = (end - start) / 60_000
  return Math.max((minutes / 60) * HOUR_HEIGHT, 20)
}

const overlapBandsByDay = computed<Record<string, OverlapBand[]>>(() => {
  const result: Record<string, OverlapBand[]> = {}
  for (const [dayKey, evs] of Object.entries(eventsByDay.value)) {
    result[dayKey] = computeOverlapBands(evs, overlapLayouts.value[dayKey] ?? {}, _topByTime, _heightByTime)
  }
  return result
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

// ─── Column HTML5 DnD drop handlers ──────────────────────────
// Track which column is hovered for visual highlight
const overDayIndex = ref<number | null>(null)
// Capture cursor position on dragover for time-slot computation in onColumnDrop
const dragPos = ref<{ y: number; rect: DOMRect } | null>(null)

function onColumnDragOver(e: DragEvent, dayIndex: number) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  overDayIndex.value = dayIndex
  if (e.currentTarget instanceof HTMLElement) {
    dragPos.value = { y: e.clientY, rect: e.currentTarget.getBoundingClientRect() }
  }
}

function onColumnDragLeave(e: DragEvent, dayIndex: number) {
  const related = e.relatedTarget as Node | null
  if (related && (e.currentTarget as HTMLElement)?.contains(related)) return
  if (overDayIndex.value === dayIndex) overDayIndex.value = null
}

async function onColumnDrop(e: DragEvent, dayIndex: number) {
  e.preventDefault()
  const pos = dragPos.value
  overDayIndex.value = null
  dragPos.value = null

  const raw = e.dataTransfer?.getData('text/plain')
  if (!raw) return

  let payload: Record<string, unknown>
  try { payload = JSON.parse(raw) } catch { return }

  const dayKey = dayKeys.value[dayIndex]
  let startDate: Date
  if (pos) {
    const relY = Math.max(0, pos.y - pos.rect.top)
    const snapY = snapToMinutes(relY, 15)
    const hour = Math.floor(snapY / HOUR_HEIGHT) + START_HOUR
    const minute = Math.round(((snapY % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15
    startDate = new Date(dayKey + 'T00:00:00')
    startDate.setHours(hour, minute, 0, 0)
  } else {
    startDate = new Date(dayKey + 'T12:00:00')
  }

  if (payload.type === 'task' && payload.taskId) {
    const taskId = payload.taskId as string
    // Look up by task_id first; fall back to event.id for standalone/synced events
    // (taskFromEvent maps event.id → task.id when task_id is null)
    const existingEvent = eventStore.events.find(ev => ev.task_id === taskId)
      ?? eventStore.events.find(ev => ev.id === taskId)
    if (existingEvent) {
      const durationMs = new Date(existingEvent.end_time).getTime() - new Date(existingEvent.start_time).getTime()
      const endDate = new Date(startDate.getTime() + durationMs)
      // Recurring occurrence: defer commit until user picks an edit scope
      if (existingEvent.is_occurrence) {
        pendingRecurrence.value = {
          kind: 'event-move',
          eventId: existingEvent.id,
          startTime: startDate.toISOString(),
          endTime: endDate.toISOString(),
          originalStartTime: existingEvent.start_time,
        }
        return
      }
      await eventStore.moveEvent(existingEvent.id, startDate.toISOString(), endDate.toISOString())
      return
    }
    const endDate = new Date(startDate.getTime() + 60 * 60_000)
    const title = (payload.title as string) ?? 'Task'
    await eventStore.promoteTask(taskId, startDate.toISOString(), endDate.toISOString(), title)
    // Refresh plan range so promoted task is removed from sidebar anchor blocks
    await planStore.fetchPlanRange(dayKeys.value[0], dayKeys.value[6])
  }
}

// ─── Sidebar anchor drop — demote event OR move task between anchors ──────────
async function onSidebarAnchorDrop(e: DragEvent, anchorId: string) {
  const raw = e.dataTransfer?.getData('application/json') || e.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const data = JSON.parse(raw)
    if (data.type === 'task' && data.taskId) {
      const taskId = data.taskId as string
      if (data.fromStartTime) {
        // Demotion path: calendar event dragged back to the sidebar (Bug C/E fix)
        // focusedDay.value is intentional — user intent is "put this on today's plan"
        const ev = eventStore.events.find(e => e.task_id === taskId)
          ?? eventStore.events.find(e => e.id === taskId)
        if (!ev) return
        await eventStore.demoteEvent(ev.id, anchorId, focusedDay.value)
        await planStore.fetchPlanRange(dayKeys.value[0], dayKeys.value[6])
      } else if (data.fromAnchorId && data.fromDate) {
        // Task→task move: dragging a sidebar task to a different anchor (Bug A/D fix)
        await planStore.moveTask(taskId, data.fromDate as string, data.fromAnchorId as string, focusedDay.value, anchorId)
        await planStore.fetchPlanRange(dayKeys.value[0], dayKeys.value[6])
      }
    }
  } catch { /* ignore malformed */ }
}

// ─── Synthetic Task from CalendarEvent ────────────────────────
// TaskCard mode="calendar-event" needs a Task prop. For task-linked events,
// return the LIVE task object from planStore so motif / status mutations from
// patchTaskFields propagate reactively to the calendar card. Only fall back to
// a synthetic object for standalone events (no task_id).
function taskFromEvent(event: CalendarEvent): Task {
  if (event.task_id) {
    // Search range cache first (populated by fetchPlanRange, used by CalendarView)
    for (const dayPlan of Object.values(planStore.plans)) {
      for (const anchor of Object.values(dayPlan.anchors)) {
        const t = anchor.tasks.find(t => t.id === event.task_id)
        if (t) return t
      }
    }
    // Fallback: single-day plan (e.g. focused day loaded separately)
    if (planStore.plan?.anchors) {
      for (const anchor of Object.values(planStore.plan.anchors)) {
        const t = anchor.tasks.find(t => t.id === event.task_id)
        if (t) return t
      }
    }
  }
  // Standalone event or task not yet in any loaded plan — synthesise minimal Task
  return {
    id: event.task_id ?? event.id,
    text: event.title,
    description: null,
    status: 'pending',
    position: 0,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: event.context_subject,
    context_node_id: null,
    anchor_id: event.anchor_id,
  }
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
  // Populate planStore.plans for the full visible week so taskFromEvent() returns
  // live reactive task objects (with motif) for every day — not just the focused day.
  planStore.fetchPlanRange(dayKeys.value[0], dayKeys.value[6])
}

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// ── Sidebar task drag-source hiding (mirrors AnchorBlock.vue:143-165) ────────
// rAF deferral lets the browser snapshot the ghost image before the source is hidden.
const draggingTaskId = ref<string | null>(null)

// ── Edge-scroll: advance calendar week when dragging to left/right edge ────────
const calendarGridRef = ref<HTMLElement | null>(null)
const { onDragOver: calendarEdgeDragOver, onDragLeave: calendarEdgeDragLeave, onDragEnd: calendarEdgeDragEnd } =
  useDragEdgeScroll(calendarGridRef, (direction) => {
    if (viewMode.value !== 'week') return
    shiftWeek(direction === 'prev' ? -7 : 7)
  })
</script>

<template>
  <div class="flex h-full bg-[--bg-canvas] text-[--fg-1] overflow-hidden">

    <!-- ── Anchor / Side Panel ── -->
    <aside
      data-testid="anchor-panel"
      class="flex-shrink-0 border-r border-[--border-1] flex flex-col transition-all duration-200 relative"
      :style="anchorPanelOpen ? { width: sidebarWidth + 'px' } : { width: '40px' }"
    >
      <!-- Toggle button -->
      <button
        data-testid="anchor-panel-toggle"
        class="flex items-center justify-center h-10 w-full border-b border-[--border-1] hover:bg-[--bg-elev-3] transition-colors text-[--fg-3] hover:text-[--fg-1] flex-shrink-0"
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
        <div class="text-xs text-[--fg-4] uppercase tracking-wide px-1 pt-1 select-none">
          {{ new Date(focusedDay + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) }}
        </div>

        <!-- Anchor blocks with task lists — also act as drop targets to demote calendar events -->
        <div
          v-for="{ anchor, tasks } in (activeFilterCount > 0 ? filteredAnchorsWithTasks : anchorsWithTasks)"
          :key="anchor.id"
          class="rounded-lg border border-[--border-soft] overflow-hidden"
          @dragover.prevent
          @drop="(e) => onSidebarAnchorDrop(e, anchor.id)"
        >
          <!-- Anchor header -->
          <div class="flex items-center gap-1.5 px-2 py-1.5" :style="{ borderLeft: `3px solid ${anchor.color}` }">
            <span class="text-xs font-medium text-[--fg-2] truncate flex-1">{{ anchor.name }}</span>
            <span class="text-[10px] text-[--fg-5]">{{ anchor.time }}</span>
          </div>
          <!-- Task list — max height + scroll so one long anchor doesn't consume the panel -->
          <ul class="flex flex-col gap-0.5 px-1 pb-1 max-h-36 overflow-y-auto">
            <li
              v-for="task in tasks"
              :key="task.id"
              v-show="draggingTaskId !== task.id"
              draggable="true"
              class="text-xs px-1.5 py-1 rounded cursor-grab hover:bg-[--bg-elev-2] text-[--fg-3] hover:text-[--fg-1] transition-colors truncate"
              :class="task.status === 'done' ? 'line-through opacity-40' : ''"
              @click.stop="pushPanel({ kind: 'task', entityId: task.id })"
              @dragstart="(e: DragEvent) => {
                if (e.dataTransfer) {
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('text/plain', JSON.stringify({
                    type: 'task',
                    taskId: task.id,
                    title: task.text,
                    fromAnchorId: anchor.id,
                    fromDate: focusedDay,
                  }))
                }
                requestAnimationFrame(() => { draggingTaskId.value = task.id })
              }"
              @dragend="draggingTaskId = null"
            >
              {{ task.text }}
            </li>
            <li v-if="!tasks.length" class="text-[11px] text-[--fg-6] px-1.5 py-0.5">No tasks</li>
          </ul>
        </div>

        <div v-if="!anchorsWithTasks.length" class="text-xs text-[--fg-5] px-1">No anchors</div>

        <div class="text-[10px] text-[--fg-6] px-1 pt-2 select-none leading-tight">
          Drag tasks into the calendar to schedule them
        </div>
      </div>

      <!-- Resize handle — only visible when panel is open -->
      <div
        v-if="anchorPanelOpen"
        class="absolute top-0 right-0 w-1 h-full cursor-col-resize hover:bg-[--accent-soft] transition-colors z-10"
        @mousedown.prevent="onResizeHandleMousedown"
      />
    </aside>

    <!-- ── Calendar Grid ── -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">

      <!-- Toolbar -->
      <header class="flex items-center gap-3 px-4 py-2 border-b border-[--border-1] flex-shrink-0">
        <h1 class="text-lg font-bold">Calendar</h1>
        <div class="flex items-center gap-1 ml-2">
          <button @click="navigatePrev" class="px-2 py-0.5 rounded hover:bg-[--bg-elev-3] text-[--fg-2] hover:text-[--fg-1] text-sm transition-colors">‹</button>
          <button @click="goToday" class="px-2 py-0.5 rounded hover:bg-[--bg-elev-3] text-[--fg-2] hover:text-[--fg-1] text-xs transition-colors">Today</button>
          <button @click="navigateNext" class="px-2 py-0.5 rounded hover:bg-[--bg-elev-3] text-[--fg-2] hover:text-[--fg-1] text-sm transition-colors">›</button>
        </div>
        <span class="text-sm text-[--fg-3]">
          {{ viewMode === 'month' ? monthLabel : weekLabel }}
        </span>
        <!-- View mode toggle -->
        <button
          data-testid="view-mode-toggle"
          class="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-xs text-[--fg-3] hover:text-[--fg-1] hover:bg-[--bg-elev-3] transition-colors border border-[--border-1]"
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
              ? 'text-[--accent] border-[--accent-soft] bg-[--accent-veil] hover:bg-[--accent-soft]'
              : 'text-[--fg-3] border-[--border-1] hover:text-[--fg-1] hover:bg-[--bg-elev-3]'"
            @click.stop="filterOpen = !filterOpen"
          >
            Filter
            <span v-if="activeFilterCount > 0" class="bg-[--accent] text-[--accent-fg] rounded-full text-[10px] px-1 leading-none py-0.5 font-bold">
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
            class="text-center text-xs text-[--fg-5] py-1"
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
              isCurrentMonth(date) ? 'bg-[--bg-elev-2] hover:bg-[--bg-elev-3]' : 'bg-[--bg-elev-1] opacity-40',
              date === today ? 'ring-1 ring-[--accent-soft]' : '',
              date === focusedDay ? 'ring-1 ring-[--accent]' : '',
            ]"
            @click="clickMonthDay(date)"
          >
            <div class="text-xs font-medium mb-1"
                 :class="date === today ? 'text-[--accent]' : 'text-[--fg-3]'">
              {{ new Date(date + 'T12:00:00').getDate() }}
            </div>
            <!-- Event pills -->
            <div class="flex flex-col gap-0.5">
              <div
                v-for="ev in eventsForDay(date).slice(0, 3)"
                :key="ev.id"
                class="rounded text-[10px] px-1 py-0.5 truncate font-medium leading-none"
                :style="{ backgroundColor: resolveColor(ev), color: textOnColor(resolveColor(ev)) }"
              >
                {{ ev.title }}
              </div>
              <div
                v-if="eventsForDay(date).length > 3"
                class="text-[10px] text-[--fg-4] px-1"
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
        <div
          ref="calendarGridRef"
          class="flex-1 overflow-y-auto"
          data-testid="calendar-grid"
          @dragover="calendarEdgeDragOver"
          @dragleave="calendarEdgeDragLeave"
          @dragend="calendarEdgeDragEnd"
        >

          <!-- Sticky header wrapper: day-of-week header + all-day band scroll together -->
          <div class="sticky top-0 z-10">

            <!-- Day-of-week header -->
            <div class="flex border-b border-[--border-1] bg-[--bg-canvas] pl-12">
              <div
                v-for="(day, i) in days"
                :key="dayKeys[i]"
                :data-testid="`day-header-${i}`"
                :data-day="dayKeys[i]"
                :data-focused="focusedDay === dayKeys[i] ? 'true' : undefined"
                class="flex-1 text-center py-1.5 text-xs cursor-pointer hover:bg-[--bg-elev-2] transition-colors select-none"
                :class="[
                  dayKeys[i] === today ? 'text-[--accent] font-semibold' : 'text-[--fg-3]',
                  focusedDay === dayKeys[i] ? 'bg-[--accent-veil]' : '',
                ]"
                @click="focusDay(dayKeys[i])"
              >
                {{ DAY_LABELS[day.getDay()] }} {{ day.getDate() }}
              </div>
            </div>

            <!-- All-day band — one row above the timed grid, one chip per is_all_day event.
                 Use opaque --bg-canvas (not the 80% veil) so timed-grid events scrolling
                 underneath don't bleed through this sticky band. -->
            <div data-testid="all-day-band" class="sticky flex border-b border-[--border-1] bg-[--bg-canvas] pl-12">
            <div
              v-for="(_, i) in days"
              :key="dayKeys[i]"
              class="flex-1 min-h-[24px] flex flex-wrap gap-0.5 px-1 py-0.5 border-l border-[--border-soft]"
            >
              <div
                v-for="ev in allDayEventsByDay[dayKeys[i]]"
                :key="ev.id"
                class="rounded text-[10px] px-1 py-0.5 truncate font-medium leading-none cursor-pointer"
                :style="{ backgroundColor: resolveColor(ev), color: textOnColor(resolveColor(ev)) }"
                data-event-block
                @click="openEventPanel(ev)"
              >
                {{ ev.title }}
              </div>
            </div>
          </div>
          </div><!-- end sticky header wrapper -->

          <div data-testid="week-view" class="flex">

            <!-- Hour labels -->
            <div class="flex-shrink-0 w-12 select-none">
              <div
                v-for="h in hours"
                :key="h"
                class="border-b border-[--border-soft] text-right pr-1 text-[10px] text-[--fg-5]"
                :style="{ height: `${HOUR_HEIGHT}px`, lineHeight: `${HOUR_HEIGHT}px` }"
              >
                {{ h === 0 ? '' : `${h % 12 || 12}${h < 12 ? 'am' : 'pm'}` }}
              </div>
            </div>

            <!-- Day columns -->
            <div
              v-for="(_, i) in days"
              :key="dayKeys[i]"
              :data-testid="`day-col-${dayKeys[i]}`"
              :data-day-col="dayKeys[i]"
              class="flex-1 relative border-l border-[--border-soft] min-w-0"
              :class="[
                overDayIndex === i ? 'bg-[--accent-veil]' : '',
                focusedDay === dayKeys[i] ? 'ring-1 ring-inset ring-[--accent-soft]' : '',
              ]"
              :style="{ height: `${HOUR_HEIGHT * (END_HOUR - START_HOUR)}px` }"
              @click.self="focusDay(dayKeys[i])"
              @mousedown="(e: MouseEvent) => onDayColumnMousedown(e, dayKeys[i])"
              @dragover="(e: DragEvent) => onColumnDragOver(e, i)"
              @dragleave="(e: DragEvent) => onColumnDragLeave(e, i)"
              @drop="(e: DragEvent) => onColumnDrop(e, i)"
            >
              <!-- Hour grid lines -->
              <div
                v-for="h in hours"
                :key="h"
                class="absolute inset-x-0 border-b border-[--border-soft]"
                :style="{ top: `${(h - START_HOUR) * HOUR_HEIGHT}px`, height: `${HOUR_HEIGHT}px` }"
              />

              <!-- Today highlight -->
              <div
                v-if="dayKeys[i] === today"
                class="absolute inset-0 bg-[--accent-veil] pointer-events-none"
              />

              <!-- Focused day highlight (stronger than today) -->
              <div
                v-if="focusedDay === dayKeys[i]"
                class="absolute inset-0 bg-[--accent-veil] pointer-events-none"
              />

              <!-- Overlap background bands — light tint over time windows with simultaneous events -->
              <div
                v-for="(band, bi) in overlapBandsByDay[dayKeys[i]]"
                :key="'overlap-bg-' + bi"
                data-testid="overlap-background"
                class="absolute inset-x-0 bg-[--bg-elev-2] pointer-events-none rounded-sm"
                :style="{ top: `${band.topPx}px`, height: `${band.heightPx}px` }"
              />

              <!-- Event blocks — TaskCard in calendar-event mode -->
              <TaskCard
                v-for="event in eventsByDay[dayKeys[i]]"
                :key="event.id"
                :task="taskFromEvent(event)"
                mode="calendar-event"
                :event="event"
                :top-px="eventTopPx(event)"
                :height-px="eventHeightPx(event)"
                :left-percent="overlapLayouts[dayKeys[i]]?.[event.id]?.leftPercent ?? 0"
                :width-percent="overlapLayouts[dayKeys[i]]?.[event.id]?.widthPercent ?? 100"
                :resolved-color="resolveColor(event)"
                data-event-block
                @click="openEventPanel(event)"
              />

              <!-- Creation drag selection rectangle -->
              <div
                v-if="creatingEvent?.dayKey === dayKeys[i] && createSelectionStyle"
                class="absolute inset-x-1 bg-blue-500/30 border border-blue-400 rounded pointer-events-none z-20"
                :style="createSelectionStyle"
              />
            </div>
          </div>
        </div>
      </template>
    </div>

    <RecurrenceEditDialog
      :visible="pendingRecurrence !== null"
      :mode="recurrenceDialogMode"
      :action="recurrenceDialogAction"
      @confirm="onRecurrenceScopeConfirm"
      @cancel="onRecurrenceScopeCancel"
    />
  </div>
</template>
