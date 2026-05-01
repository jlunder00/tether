<script setup lang="ts">
import { computed, watch, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore, computeAnchorStates } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { useEventStore } from '../stores/events'
import { useSlideOver } from '../composables/useSlideOver'
import AnchorBlock from '../components/AnchorBlock.vue'
import WeekView from '../components/WeekView.vue'
import MonthView from '../components/MonthView.vue'
import DayTimeline from '../components/DayTimeline.vue'
import type { CalendarEvent } from '../types/events'

const props = defineProps<{ view: string; date?: string }>()
const router = useRouter()
const planStore = usePlanStore()
const anchorStore = useAnchorStore()

// Reactive clock — drives current/past/future dot states
const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | null = null
const anchorStates = computed(() => computeAnchorStates(anchorStore.anchors, now.value))
const milestoneStore = useMilestoneStore()
const eventStore = useEventStore()
const { push: pushPanel } = useSlideOver()

// Resolve date from route or default to today
const activeDate = computed(() => (props.date as string) || planStore.today)

const isToday = computed(() => activeDate.value === planStore.today)

const displayDate = computed(() => {
  const diff = Math.round(
    (new Date(activeDate.value + 'T12:00:00').getTime() -
     new Date(planStore.today + 'T12:00:00').getTime()) / 86400000
  )
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  const d = new Date(activeDate.value + 'T12:00:00')
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
})

// Fetch plan when date changes
watch(activeDate, (d) => planStore.fetchPlan(d), { immediate: true })
onMounted(() => {
  anchorStore.fetchAnchors()
  milestoneStore.fetchAll()
  clockTimer = setInterval(() => { now.value = new Date() }, 60_000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})

function offsetDate(base: string, days: number): string {
  const d = new Date(base + 'T12:00:00')
  d.setDate(d.getDate() + days)
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function goToDate(date: string) {
  router.push(`/plan/${props.view}/${date}`)
}

function prevDay() {
  goToDate(offsetDate(activeDate.value, -1))
}

function nextDay() {
  goToDate(offsetDate(activeDate.value, +1))
}

function goToday() {
  goToDate(planStore.today)
}

async function onCreateAt(isoTime: string) {
  // Create a new task then promote it to a calendar event at the chosen time
  const endTime = new Date(new Date(isoTime).getTime() + 30 * 60_000).toISOString()
  const taskId = await eventStore.createTaskAndPromote(isoTime, endTime)
  if (taskId) {
    pushPanel({ kind: 'task', entityId: taskId })
  }
}

function onOpenEvent(event: CalendarEvent) {
  if (event.task_id) {
    pushPanel({ kind: 'task', entityId: event.task_id })
  }
}

/** Handle drop of a calendar event onto the anchor column — demotes it back to a plain task. */
async function onAnchorColumnDrop(e: DragEvent) {
  // DayTimeline writes both application/json and text/plain; prefer application/json
  const rawJson = e.dataTransfer?.getData('application/json')
  const rawText = e.dataTransfer?.getData('text/plain')
  const raw = rawJson || rawText
  if (!raw) return
  try {
    const data = JSON.parse(raw)
    if (data.type === 'calendar-event' && data.eventId) {
      // Use the event's original anchor if available; fall back to first anchor
      const anchorId = data.anchorId ?? anchorStore.anchors[0]?.id ?? ''
      await eventStore.demoteEvent(data.eventId, anchorId, activeDate.value)
      // Refresh plan so the demoted task appears in anchor blocks
      await planStore.fetchPlan(activeDate.value)
    }
  } catch {
    // ignore malformed drag data
  }
}
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="flex items-center gap-2 mt-1">
          <template v-if="props.view === 'day'">
            <button @click="prevDay"
                    class="text-[--fg-4] hover:text-[--fg-1] text-lg leading-none px-1">‹</button>
            <span class="text-sm font-medium min-w-[90px] text-center">{{ displayDate }}</span>
            <button @click="nextDay"
                    class="text-[--fg-4] hover:text-[--fg-1] text-lg leading-none px-1">›</button>
            <button v-if="!isToday" @click="goToday"
                    class="text-xs text-[--fg-4] hover:text-[--fg-1] ml-1 border border-[--border-1] rounded px-2 py-0.5">
              Today
            </button>
          </template>
          <template v-else>
            <span class="text-sm text-[--fg-3]">{{ props.view === 'week' ? 'Week' : 'Month' }} view</span>
          </template>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- Zoom controls -->
        <div class="flex gap-1 bg-[--bg-elev-1] rounded-lg p-0.5">
          <router-link :to="'/plan/day/' + activeDate"
                       :class="props.view === 'day' ? 'bg-[--bg-elev-2] text-[--fg-1]' : 'text-[--fg-4] hover:text-[--fg-2]'"
                       class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            D
          </router-link>
          <router-link :to="'/plan/week/' + activeDate"
                       :class="props.view === 'week' ? 'bg-[--bg-elev-2] text-[--fg-1]' : 'text-[--fg-4] hover:text-[--fg-2]'"
                       class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            W
          </router-link>
          <router-link :to="'/plan/month/' + activeDate"
                       :class="props.view === 'month' ? 'bg-[--bg-elev-2] text-[--fg-1]' : 'text-[--fg-4] hover:text-[--fg-2]'"
                       class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            M
          </router-link>
        </div>
      </div>
    </div>

    <!-- Week view -->
    <WeekView v-if="props.view === 'week'" />

    <!-- Month view -->
    <MonthView v-else-if="props.view === 'month'" />

    <!-- Day view: two-column layout -->
    <template v-else>
      <div v-if="planStore.loading" class="text-[--fg-4]">Loading...</div>
      <!-- Two-column: anchor blocks left, day timeline right -->
      <div v-else class="grid grid-cols-[1fr_320px] gap-4 items-start">
        <!-- Left: anchor blocks -->
        <div
          class="flex flex-col"
          @dragover.prevent
          @drop="onAnchorColumnDrop"
        >
          <AnchorBlock
            v-for="(anchor, i) in anchorStore.anchors"
            :key="anchor.id"
            :anchor-id="anchor.id"
            :anchor-name="anchor.name"
            :time="anchor.time"
            :color="anchor.color"
            :motif="anchor.motif"
            :is-now="anchorStates.get(anchor.id) === 'now'"
            :is-past="anchorStates.get(anchor.id) === 'past'"
            :is-last="i === anchorStore.anchors.length - 1" />
        </div>
        <!-- Right: day timeline -->
        <DayTimeline
          :date="activeDate"
          @create-at="onCreateAt"
          @open-event="onOpenEvent"
        />
      </div>
    </template>

    <!-- Child route detail panels -->
    <router-view />
  </div>
</template>
