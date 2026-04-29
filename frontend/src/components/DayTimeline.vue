<script setup lang="ts">
import { computed, watch, onMounted, ref, nextTick } from 'vue'
import { useEventStore } from '../stores/events'
import { useAnchorStore } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { useContextStore } from '../stores/context'
import CalendarEventBlock from './CalendarEventBlock.vue'
import RecurrenceEditDialog from './RecurrenceEditDialog.vue'
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

function resolveColor(ev: CalendarEvent): string {
  return resolveEventColor(ev, milestoneStore.all, contextStore.nodes)
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

// --- Drag / move state ---

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

// --- Drag-to-move (vertical) ---

// draggingEvent tracks the event being dragged and the initial cursor offset.
// justDragged guards against the browser firing a trailing click after mouseup.
const draggingEvent = ref<{
  event: CalendarEvent
  startY: number
  origTopPx: number
  durationMin: number
} | null>(null)

const dragOffsetY = ref(0)
const justDragged = ref(false)

function onEventMousedown(event: CalendarEvent, mouseEvent: MouseEvent) {
  const top = eventTopPx(event.start_time)
  const dur = (new Date(event.end_time).getTime() - new Date(event.start_time).getTime()) / 60_000
  draggingEvent.value = {
    event,
    startY: mouseEvent.clientY,
    origTopPx: top,
    durationMin: dur,
  }
  dragOffsetY.value = 0

  const onMove = (e: MouseEvent) => {
    if (!draggingEvent.value) return
    dragOffsetY.value = e.clientY - draggingEvent.value.startY
  }

  const onUp = async (e: MouseEvent) => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    if (!draggingEvent.value) return

    const deltaMin = Math.round((e.clientY - draggingEvent.value.startY) / PX_PER_MINUTE / 15) * 15
    if (deltaMin === 0) {
      draggingEvent.value = null
      return
    }

    // Set guard BEFORE clearing draggingEvent so the trailing click is blocked.
    // Clear it after nextTick once the click event has been processed.
    justDragged.value = true
    const origStart = new Date(draggingEvent.value.event.start_time)
    const origEnd = new Date(draggingEvent.value.event.end_time)
    const newStart = new Date(origStart.getTime() + deltaMin * 60_000)
    const newEnd = new Date(origEnd.getTime() + deltaMin * 60_000)

    const ev = draggingEvent.value.event
    draggingEvent.value = null
    await handleEventMove(ev, newStart.toISOString(), newEnd.toISOString())
    await nextTick()
    justDragged.value = false
  }

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// --- Click-to-create ---

function onTimedAreaClick(e: MouseEvent) {
  // Block click fired immediately after a drag-end (mouseup → click ordering)
  if (justDragged.value) return
  // Also block if we're mid-drag (shouldn't happen, but guard anyway)
  if (draggingEvent.value) return

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

/** Format a Date as local-naive ISO (YYYY-MM-DDTHH:MM) — no timezone offset. */
function toLocalIso(d: Date): string {
  const year = d.getFullYear()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${year}-${mo}-${day}T${hh}:${mm}`
}

// --- Drop from anchor block (task promotion) ---
// Note: drag of event block to LEFT column (demote) is handled by PlanView droptarget

async function onTimedAreaDrop(e: DragEvent) {
  e.preventDefault()
  // AnchorBlock writes 'text/plain'; we also accept 'application/json' for future-proofing.
  // Try application/json first, fall back to text/plain.
  const rawJson = e.dataTransfer?.getData('application/json')
  const rawText = e.dataTransfer?.getData('text/plain')
  const raw = rawJson || rawText
  if (!raw) return
  try {
    const data = JSON.parse(raw)
    // AnchorBlock drag payload: { taskId, title, fromAnchorId, fromDate }
    // Check for taskId directly (AnchorBlock format) or type:'task' (application/json format)
    const isTask = data.taskId && (data.type === 'task' || data.fromAnchorId !== undefined)
    if (isTask) {
      // Compute drop time from cursor position — use local ISO to match click-create format
      const target = e.currentTarget as HTMLElement
      const rect = target.getBoundingClientRect()
      const offsetY = e.clientY - rect.top + target.scrollTop
      const rawMin = offsetY / PX_PER_MINUTE
      const snappedMin = Math.round(rawMin / 15) * 15

      const d = new Date(props.date + 'T00:00:00')
      d.setHours(AXIS_START_HOUR, 0, 0, 0)
      d.setMinutes(d.getMinutes() + snappedMin)
      const startISO = toLocalIso(d)
      const endD = new Date(d.getTime() + 30 * 60_000)
      const endISO = toLocalIso(endD)

      // TODO: if task is recurring, show RecurrenceEditDialog with title "Edit recurring task: move to timeline?"
      await eventStore.promoteTask(data.taskId, startISO, endISO, data.title ?? data.taskId)
    }
  } catch {
    // ignore malformed drag data
  }
}

// --- Drag event block (for demote: drag to left anchor column) ---

function onEventDragstart(event: CalendarEvent, dragEvent: DragEvent) {
  dragEvent.dataTransfer!.effectAllowed = 'move'
  // Include anchor_id so the drop target can return the task to its original anchor
  const payload = JSON.stringify({
    type: 'calendar-event',
    eventId: event.id,
    taskId: event.task_id,
    title: event.title,
    anchorId: event.anchor_id,
  })
  dragEvent.dataTransfer!.setData('application/json', payload)
  dragEvent.dataTransfer!.setData('text/plain', payload)
}

function onDragover(e: DragEvent) {
  e.preventDefault()
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

// --- Event block helpers ---

function timedEventStyle(event: CalendarEvent) {
  const layout = overlapLayout.value[event.id]
  const leftPct = layout?.leftPercent ?? 0
  const widthPct = layout?.widthPercent ?? 100
  return {
    left: `${leftPct}%`,
    width: `calc(${widthPct}% - 4px)`,
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
      @dragover="onDragover"
      @drop="onTimedAreaDrop"
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

        <!-- Overlap background bands — light tint indicating simultaneous events -->
        <div
          v-for="(band, bi) in overlapBands"
          :key="'overlap-' + bi"
          data-testid="overlap-background"
          class="absolute inset-x-0 bg-white/5 pointer-events-none rounded-sm"
          :style="{ top: `${band.topPx}px`, height: `${band.heightPx}px` }"
        />

        <!-- Hour grid lines -->
        <div
          v-for="{ hour } in hourLabels"
          :key="'line-' + hour"
          class="absolute inset-x-0 border-t border-[--border-soft] pointer-events-none"
          :style="{ top: `${(hour - AXIS_START_HOUR) * 60 * PX_PER_MINUTE}px` }"
        />

        <!--
          Timed event wrapper.
          Layout: an absolute positioned container holds two children:
            1. A narrow left-edge grip strip — has draggable="true" for HTML5 demote-to-sidebar drag.
               HTML5 drag suppresses mousemove once started (Chromium/WebKit), so it lives on its
               own element, separate from the mousedown-based vertical reposition.
            2. CalendarEventBlock — handles mousedown (vertical reposition) and click (open panel).
               No draggable attr here so the browser's drag threshold never cancels mousemove.
        -->
        <div
          v-for="ev in timedEvents"
          :key="ev.id"
          class="absolute flex"
          :style="{
            top: `${eventTopPx(ev.start_time)}px`,
            left: timedEventStyle(ev).left,
            width: timedEventStyle(ev).width,
            height: `${eventHeightPx(ev.start_time, ev.end_time)}px`,
          }"
        >
          <!-- Drag grip (HTML5 demote drag) — narrow left strip -->
          <div
            class="flex-shrink-0 w-2 cursor-grab z-20 rounded-l opacity-0 hover:opacity-100 bg-white/20 transition-opacity"
            :title="'Drag to anchor column to un-schedule'"
            draggable="true"
            @dragstart.stop="(de) => onEventDragstart(ev, de)"
          />
          <!-- Event block body — mousedown for vertical reposition only, no draggable -->
          <CalendarEventBlock
            class="flex-1 min-w-0"
            :event="ev"
            :top-px="0"
            :height-px="eventHeightPx(ev.start_time, ev.end_time)"
            :resolved-color="resolveColor(ev)"
            @click="emit('open-event', ev)"
            @mousedown="(me) => onEventMousedown(ev, me)"
          />
        </div>
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
