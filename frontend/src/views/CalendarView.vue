<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAnchorStore } from '../stores/anchors'
import { useEventStore } from '../stores/events'
import { usePlanStore } from '../stores/plan'
import type { CalendarEvent } from '../types/events'
import type { Anchor } from '../stores/anchors'

const anchorStore = useAnchorStore()
const eventStore = useEventStore()
const planStore = usePlanStore()

// ─── View state ───────────────────────────────────────────────
const anchorPanelOpen = ref(true)

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

const days = computed<Date[]>(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    return d
  }),
)

// Cached keys so we don't recompute localDateString for every cell on every render.
const dayKeys = computed(() => days.value.map(localDateString))

function shiftWeek(deltaDays: number) {
  const d = new Date(weekStart.value)
  d.setDate(d.getDate() + deltaDays)
  weekStart.value = d
  loadEvents()
}

function goToday() {
  weekStart.value = getWeekStart(new Date())
  loadEvents()
}

// ─── Focused day for anchor panel ─────────────────────────────
const focusedDay = ref(today)

// ─── Hours displayed in grid ──────────────────────────────────
const HOUR_HEIGHT = 60 // px per hour
const START_HOUR = 0
const END_HOUR = 24

const hours = Array.from({ length: END_HOUR - START_HOUR }, (_, i) => START_HOUR + i)

// ─── Events mapped per day ────────────────────────────────────
const eventsByDay = computed(() => {
  const map: Record<string, CalendarEvent[]> = {}
  for (const key of dayKeys.value) {
    map[key] = eventStore.events.filter(e => e.start_time.startsWith(key))
  }
  return map
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

function eventColor(event: CalendarEvent): string {
  if (event.source !== 'tether') return '#4285f4' // Google blue for synced
  return event.color ?? '#6366f1' // indigo default
}

// ─── Anchor panel: tasks for focused day ──────────────────────
const anchorsWithTasks = computed(() => {
  const plan = planStore.plans[focusedDay.value] ?? planStore.plan
  if (!plan) return []
  return anchorStore.anchors.map((a: Anchor) => ({
    anchor: a,
    tasks: plan.anchors[a.id]?.tasks ?? [],
  }))
})

// ─── Drag-to-promote: task → event ────────────────────────────
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

  let taskId: string | undefined
  try { taskId = JSON.parse(raw).taskId } catch { return }
  if (!taskId) return

  // Find task title in current plan; fall back to 'Task' for backlog/unknown.
  let title = 'Task'
  for (const anchorPlan of Object.values(planStore.plan?.anchors ?? {})) {
    const found = anchorPlan.tasks.find(t => t.id === taskId)
    if (found) { title = found.text; break }
  }

  // Map drop position to a quarter-hour slot.
  const rect = e.currentTarget.getBoundingClientRect()
  const relY = e.clientY - rect.top
  const hour = Math.floor(relY / HOUR_HEIGHT) + START_HOUR
  const minute = Math.round(((relY % HOUR_HEIGHT) / HOUR_HEIGHT) * 60 / 15) * 15

  const startDate = new Date(day)
  startDate.setHours(hour, minute, 0, 0)
  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000) // 1 hour default

  await eventStore.promoteTask(taskId, startDate.toISOString(), endDate.toISOString(), title)
}

// ─── Data loading ──────────────────────────────────────────────
function loadEvents() {
  eventStore.fetchEvents(dayKeys.value[0], dayKeys.value[6])
}

onMounted(() => {
  anchorStore.fetchAnchors()
  planStore.fetchPlan(focusedDay.value)
  loadEvents()
})

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
</script>

<template>
  <div class="flex h-full bg-gray-900 text-white overflow-hidden">

    <!-- ── Anchor / Side Panel ── -->
    <aside
      data-testid="anchor-panel"
      class="flex-shrink-0 border-r border-white/10 flex flex-col transition-all duration-200"
      :class="anchorPanelOpen ? 'w-56' : 'w-10'"
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

      <!-- Panel content -->
      <div v-if="anchorPanelOpen" data-testid="anchor-panel-content" class="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        <!-- Focused day label -->
        <div class="text-xs text-white/40 uppercase tracking-wide px-1 pt-1 select-none">
          {{ new Date(focusedDay + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) }}
        </div>

        <!-- Anchor blocks with task lists -->
        <div
          v-for="{ anchor, tasks } in anchorsWithTasks"
          :key="anchor.id"
          class="rounded-lg border border-white/5 overflow-hidden"
        >
          <!-- Anchor header -->
          <div class="flex items-center gap-1.5 px-2 py-1.5" :style="{ borderLeft: `3px solid ${anchor.color}` }">
            <span class="text-xs font-medium text-white/80 truncate flex-1">{{ anchor.name }}</span>
            <span class="text-[10px] text-white/30">{{ anchor.time }}</span>
          </div>
          <!-- Task list -->
          <ul class="flex flex-col gap-0.5 px-1 pb-1">
            <li
              v-for="task in tasks"
              :key="task.id"
              draggable="true"
              class="text-xs px-1.5 py-1 rounded cursor-grab hover:bg-white/5 text-white/60 hover:text-white/90 transition-colors truncate"
              :class="task.status === 'done' ? 'line-through opacity-40' : ''"
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
    </aside>

    <!-- ── Calendar Grid ── -->
    <div class="flex-1 flex flex-col min-w-0 overflow-hidden">

      <!-- Toolbar -->
      <header class="flex items-center gap-3 px-4 py-2 border-b border-white/10 flex-shrink-0">
        <h1 class="text-lg font-bold">Calendar</h1>
        <div class="flex items-center gap-1 ml-2">
          <button @click="shiftWeek(-7)" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-sm transition-colors">‹</button>
          <button @click="goToday" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-xs transition-colors">Today</button>
          <button @click="shiftWeek(7)" class="px-2 py-0.5 rounded hover:bg-white/10 text-white/60 hover:text-white text-sm transition-colors">›</button>
        </div>
        <span class="text-sm text-white/50">
          {{ days[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) }}
          – {{ days[6].toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) }}
        </span>
      </header>

      <!-- Day-of-week header -->
      <div class="flex flex-shrink-0 border-b border-white/10" style="padding-left: 48px">
        <div
          v-for="(day, i) in days"
          :key="dayKeys[i]"
          class="flex-1 text-center py-1.5 text-xs cursor-pointer hover:bg-white/5 transition-colors"
          :class="dayKeys[i] === today ? 'text-indigo-400 font-semibold' : 'text-white/50'"
          @click="focusedDay = dayKeys[i]; planStore.fetchPlan(dayKeys[i])"
        >
          {{ DAY_LABELS[day.getDay()] }} {{ day.getDate() }}
        </div>
      </div>

      <!-- Scrollable time grid -->
      <div class="flex-1 overflow-y-auto" data-testid="calendar-grid">
        <div class="flex" style="min-height: 100%">

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
            class="flex-1 relative border-l border-white/5 min-w-0"
            :class="dragOverDay === dayKeys[i] ? 'bg-indigo-500/10' : ''"
            :style="{ height: `${HOUR_HEIGHT * (END_HOUR - START_HOUR)}px` }"
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

            <!-- Event blocks -->
            <div
              v-for="event in eventsByDay[dayKeys[i]]"
              :key="event.id"
              class="absolute inset-x-1 rounded overflow-hidden text-xs px-1.5 py-0.5 cursor-pointer shadow-md hover:brightness-110 transition-all z-10"
              :style="{
                top: `${eventTopPx(event)}px`,
                height: `${eventHeightPx(event)}px`,
                backgroundColor: eventColor(event),
                opacity: event.source !== 'tether' ? 0.75 : 1,
              }"
            >
              <div class="flex items-center gap-1 truncate">
                <!-- Provider badge for synced events -->
                <span v-if="event.source !== 'tether'" class="text-[9px] bg-black/20 rounded px-0.5 flex-shrink-0" title="Synced from external calendar">
                  {{ event.source === 'google_calendar' ? 'G' : '↗' }}
                </span>
                <span class="truncate font-medium text-white">{{ event.title }}</span>
              </div>
            </div>

            <!-- Drop indicator -->
            <div
              v-if="dragOverDay === dayKeys[i] && dragOverHour !== null"
              class="absolute inset-x-1 h-0.5 bg-indigo-400 rounded pointer-events-none z-20"
              :style="{ top: `${(dragOverHour! - START_HOUR) * HOUR_HEIGHT}px` }"
            />
          </div>
        </div>
      </div>
    </div>

    <router-view />
  </div>
</template>
