<script setup lang="ts">
import { computed, watch, onMounted, ref, nextTick } from 'vue'
import { useEventStore } from '../stores/events'
import { useAnchorStore } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { useContextStore } from '../stores/context'
import { usePlanStore } from '../stores/plan'
import type { Task } from '../stores/plan'
import RecurrenceEditDialog from './RecurrenceEditDialog.vue'
import TaskCard from './TaskCard.vue'
import {
  eventTopPx,
  eventHeightPx,
  anchorBandTopPx,
  anchorBandHeightPx,
  computeAnchorOverlapLayout,
  AXIS_START_HOUR,
  AXIS_END_HOUR,
  AXIS_TOTAL_PX,
  PX_PER_MINUTE,
} from '../composables/useDayTimeline'
import { computeOverlapLayout, computeOverlapBands } from '../composables/useOverlapLayout'
import { resolveEventColor } from '../composables/useColorResolver'
import type { CalendarEvent } from '../types/events'
import type { RecurrenceEditScope } from '../types/recurrence'
import type { DropPayload } from '../composables/useDropZone'

const props = defineProps<{
  date: string  // YYYY-MM-DD
}>()

const emit = defineEmits<{
  (e: 'create-at', isoTime: string): void
  (e: 'open-event', event: CalendarEvent): void
}>()

const eventStore = useEventStore()
const anchorStore = useAnchorStore()
const milestoneStore = useMilestoneStore()
const contextStore = useContextStore()
const planStore = usePlanStore()

function resolveColor(ev: CalendarEvent): string {
  return resolveEventColor(ev, milestoneStore.all, contextStore.nodes)
}

function taskFromEvent(ev: CalendarEvent): Task {
  // For task-linked events, return live Task from planStore for reactive motif/status
  if (ev.task_id && planStore.plan?.anchors) {
    for (const anchor of Object.values(planStore.plan.anchors)) {
      const t = anchor.tasks.find(t => t.id === ev.task_id)
      if (t) return t
    }
  }
  // Standalone event or task not in today's plan — synthesise minimal Task
  return {
    id: ev.task_id ?? ev.id,
    text: ev.title,
    description: null,
    status: 'pending',
    position: 0,
    followup_config: null,
    blocks: [],
    blocked_by: [],
    context_subject: ev.context_subject,
    context_node_id: null,
    anchor_id: ev.anchor_id,
    color: null,
    motif: null,
  }
}

// --- Date parsing ---

const dateObj = computed(() => new Date(props.date + 'T12:00:00'))

// --- Events split by type ---

const allDayEvents = computed(() =>
  eventStore.events.filter(ev => ev.is_all_day === true)
)

const timedEvents = computed(() =>
  eventStore.events.filter(ev => ev.is_all_day !== true)
)

// --- Overlap layout for timed events ---

const overlapLayout = computed(() => computeOverlapLayout(timedEvents.value))

// --- Overlap background bands (time windows with multiple concurrent events) ---

const overlapBands = computed(() =>
  computeOverlapBands(timedEvents.value, overlapLayout.value, eventTopPx, eventHeightPx)
)

// --- Anchor band overlap layout ---

const anchorOverlapLayouts = computed(() =>
  computeAnchorOverlapLayout(anchorStore.anchors, dateObj.value)
)

// --- Hour labels (6am..11pm) ---

const hourLabels = computed(() => {
  const labels: { hour: number; label: string }[] = []
  for (let h = AXIS_START_HOUR; h < AXIS_END_HOUR; h++) {
    const suffix = h < 12 ? 'am' : 'pm'
    const display = h === 12 ? 12 : h > 12 ? h - 12 : h
    labels.push({ hour: h, label: `${display}${suffix}` })
  }
  return labels
})

// --- Fetch events on mount and when date changes ---

function fetchForDate(date: string) {
  const start = date + 'T00:00:00'
  const end = date + 'T23:59:59'
  eventStore.fetchEvents(start, end)
}

onMounted(() => {
  fetchForDate(props.date)
  // Auto-scroll to current time (100px buffer above)
  nextTick(() => {
    if (!timedAreaEl.value) return
    const now = new Date()
    const minutesFromAxisStart = (now.getHours() - AXIS_START_HOUR) * 60 + now.getMinutes()
    if (minutesFromAxisStart > 0) {
      const topPxNow = minutesFromAxisStart * PX_PER_MINUTE
      timedAreaEl.value.scrollTop = Math.max(0, topPxNow - 100)
    }
  })
})
watch(() => props.date, fetchForDate)

// --- Timed area ref for auto-scroll ---
const timedAreaEl = ref<HTMLElement | null>(null)

const showRecurrenceDialog = ref(false)
const pendingMove = ref<{ event: CalendarEvent; newStart: string; newEnd: string } | null>(null)

async function handleEventMove(event: CalendarEvent, newStart: string, newEnd: string) {
  if (event.is_recurring || event.is_occurrence) {
    pendingMove.value = { event, newStart, newEnd }
    showRecurrenceDialog.value = true
    return
  }
  await eventStore.moveEvent(event.id, newStart, newEnd)
}

async function onRecurrenceConfirm(_scope: RecurrenceEditScope) {
  showRecurrenceDialog.value = false
  if (!pendingMove.value) return
  const { event, newStart, newEnd } = pendingMove.value
  // TODO: pass scope to backend when backend supports it
  await eventStore.moveEvent(event.id, newStart, newEnd)
  pendingMove.value = null
}

function onRecurrenceCancel() {
  showRecurrenceDialog.value = false
  pendingMove.value = null
}

// --- 15-min slot drop zones ---

const SLOT_COUNT = (AXIS_END_HOUR - AXIS_START_HOUR) * 4  // e.g. 18h x 4 = 72

/** Format slot index as 'HH:MM'. Slot 0 = AXIS_START_HOUR:00. */
function slotTime(i: number): string {
  const totalMin = i * 15 + AXIS_START_HOUR * 60
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

async function handleSlotDrop(payload: DropPayload, time: string) {
  const slotStart = `${props.date}T${time}:00`
  const slotStartMs = new Date(slotStart).getTime()

  // type === 'task' handles both plan-view promotions AND calendar-event repositions
  // (useDraggableTask always writes type:'task'; fromStartTime present <-> calendar event)
  const taskId = (payload as { taskId?: string }).taskId
  if (!taskId) return
  const title = (payload as { title?: string }).title ?? taskId
  // Dual lookup: task_id for task-linked events; id for standalone events
  const existing = eventStore.events.find(e => e.task_id === taskId)
    ?? eventStore.events.find(e => e.id === taskId)
  if (existing) {
    const dur = new Date(existing.end_time).getTime() - new Date(existing.start_time).getTime()
    const newEnd = toLocalIso(new Date(slotStartMs + (dur || 30 * 60_000)))
    await handleEventMove(existing, slotStart, newEnd)
  } else {
    const endISO = toLocalIso(new Date(slotStartMs + 30 * 60_000))
    await eventStore.promoteTask(taskId, slotStart, endISO, title)
  }
}

/** Index of the currently hovered slot (for drop-zone highlight), or null. */
const overSlotIndex = ref<number | null>(null)

function onSlotDragOver(e: DragEvent, i: number) {
  e.preventDefault()
  overSlotIndex.value = i
}

function onSlotDragLeave(e: DragEvent, i: number) {
  // Only clear when leaving the element entirely (not entering a child)
  const related = e.relatedTarget as Node | null
  if (related && (e.currentTarget as HTMLElement).contains(related)) return
  if (overSlotIndex.value === i) overSlotIndex.value = null
}

async function onSlotDrop(e: DragEvent, i: number) {
  e.preventDefault()
  overSlotIndex.value = null
  const rawJson = e.dataTransfer?.getData('application/json')
  const rawText = e.dataTransfer?.getData('text/plain')
  const raw = rawJson || rawText
  if (!raw) return
  try {
    await handleSlotDrop(JSON.parse(raw), slotTime(i))
  } catch { /* ignore malformed payload */ }
}

// Array used purely for v-for slot grid rendering
const slotIndices = Array.from({ length: SLOT_COUNT }, (_, i) => i)

// --- Click-to-create ---

function onTimedAreaClick(e: MouseEvent) {
  const target = e.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const offsetY = e.clientY - rect.top + target.scrollTop

  // Convert px offset to minutes from axis start, snap to 15 min
  const rawMin = offsetY / PX_PER_MINUTE
  const snappedMin = Math.round(rawMin / 15) * 15

  const d = new Date(props.date + 'T00:00:00')
  d.setHours(AXIS_START_HOUR, 0, 0, 0)
  d.setMinutes(d.getMinutes() + snappedMin)

  emit('create-at', toLocalIso(d))
}

// --- Time formatting helpers ---

/** Format a Date as local-naive ISO (YYYY-MM-DDTHH:MM) -- no timezone offset. */
function toLocalIso(d: Date): string {
  const year = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${year}-${mo}-${day}T${hh}:${mm}`
}

// --- Anchor color helper ---

function anchorBandStyle(anchor: { color: string; id: string }) {
  const layout = anchorOverlapLayouts.value[anchor.id] ?? { leftPercent: 0, widthPercent: 100 }
  return {
    background: 'var(--m-band)',
    borderLeft: '2px solid var(--m)',
    top: `${anchorBandTopPx(anchor as Parameters<typeof anchorBandTopPx>[0], dateObj.value)}px`,
    height: `${anchorBandHeightPx(anchor as Parameters<typeof anchorBandHeightPx>[0], dateObj.value)}px`,
    left: `${layout.leftPercent}%`,
    width: `${layout.widthPercent}%`,
  }
}
</script>

<template>
  <div data-testid="day-timeline" class="flex flex-col bg-[--bg-elev-1] border border-[--border-1] rounded-lg overflow-hidden select-none">
    <!-- All-day events strip -->
    <div
      data-testid="allday-strip"
      class="flex flex-col gap-0.5 px-2 py-1 border-b border-[--border-1] min-h-[28px]"
    >
      <div
        v-for="ev in allDayEvents"
        :key="ev.id"
        class="text-xs px-1.5 py-0.5 rounded text-[--fg-1] truncate cursor-pointer"
        :style="{ backgroundColor: ev.color ?? '#6366f1' }"
        @click="emit('open-event', ev)"
      >
        {{ ev.title }}
      </div>
    </div>

    <!-- Timed area -->
    <div
      ref="timedAreaEl"
      data-testid="timed-area"
      class="relative flex overflow-y-auto"
      :style="{ height: 'calc(100vh - 200px)' }"
      @click="onTimedAreaClick"
    >
      <!-- Hour grid + labels -->
      <div class="relative flex-shrink-0 w-10" :style="{ height: `${AXIS_TOTAL_PX}px` }">
        <div
          v-for="{ hour, label } in hourLabels"
          :key="hour"
          :data-testid="`time-label-${hour}`"
          class="absolute right-1 text-[10px] text-[--fg-5] leading-none"
          :style="{ top: `${(hour - AXIS_START_HOUR) * 60 * PX_PER_MINUTE}px` }"
        >
          {{ label }}
        </div>
      </div>

      <!-- Event + anchor band area -->
      <div class="relative flex-1" :style="{ height: `${AXIS_TOTAL_PX}px` }">
        <!-- Anchor background bands -->
        <div
          v-for="anchor in anchorStore.anchors"
          :key="anchor.id"
          :data-motif="anchor.motif ?? 'anchor'"
          :data-testid="`anchor-band-${anchor.id}`"
          class="absolute pointer-events-none rounded-sm"
          :style="anchorBandStyle(anchor)"
        />

        <!-- Overlap background bands -- light tint indicating simultaneous events -->
        <div
          v-for="(band, bi) in overlapBands"
          :key="'overlap-' + bi"
          data-testid="overlap-background"
          class="absolute inset-x-0 bg-[--bg-elev-1] pointer-events-none rounded-sm"
          :style="{ top: `${band.topPx}px`, height: `${band.heightPx}px` }"
        />

        <!-- Hour grid lines -->
        <div
          v-for="{ hour } in hourLabels"
          :key="'line-' + hour"
          class="absolute inset-x-0 border-t border-[--border-soft] pointer-events-none"
          :style="{ top: `${(hour - AXIS_START_HOUR) * 60 * PX_PER_MINUTE}px` }"
        />

        <!-- 15-min slot drop targets -- transparent absolute divs at each 15-min interval -->
        <div
          v-for="i in slotIndices"
          :key="'slot-' + i"
          data-time-slot
          :data-date="date"
          :data-time="slotTime(i)"
          class="absolute inset-x-0 transition-colors"
          :class="{ 'ring-1 ring-[--accent] bg-[--accent]/10 z-30': overSlotIndex === i }"
          :style="{
            top: `${i * 15 * PX_PER_MINUTE}px`,
            height: `${15 * PX_PER_MINUTE}px`,
          }"
          @dragover="(e) => onSlotDragOver(e, i)"
          @dragleave="(e) => onSlotDragLeave(e, i)"
          @drop="(e) => onSlotDrop(e, i)"
        />

        <!-- Timed event blocks -- TaskCard in calendar-event mode -->
        <TaskCard
          v-for="ev in timedEvents"
          :key="ev.id"
          :task="taskFromEvent(ev)"
          mode="calendar-event"
          :event="ev"
          :top-px="eventTopPx(ev.start_time)"
          :height-px="eventHeightPx(ev.start_time, ev.end_time)"
          :left-percent="overlapLayout[ev.id]?.leftPercent ?? 0"
          :width-percent="overlapLayout[ev.id]?.widthPercent ?? 100"
          :resolved-color="resolveColor(ev)"
          data-event-block
          @click.stop="emit('open-event', ev)"
        />
      </div>
    </div>

    <!-- Recurrence edit dialog -->
    <RecurrenceEditDialog
      :visible="showRecurrenceDialog"
      mode="event"
      action="move"
      @confirm="onRecurrenceConfirm"
      @cancel="onRecurrenceCancel"
    />
  </div>
</template>
