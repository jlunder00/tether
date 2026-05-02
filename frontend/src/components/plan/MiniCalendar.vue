<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { usePlanStore } from '../../stores/plan'
import { useAnchorStore } from '../../stores/anchors'
import MiniCalendarDay from './MiniCalendarDay.vue'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const viewDate = ref(new Date(planStore.activeDate + 'T12:00:00'))

const monthLabel = computed(() =>
  viewDate.value.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
)

function prevMonth() {
  const d = new Date(viewDate.value)
  d.setMonth(d.getMonth() - 1)
  viewDate.value = d
}

function nextMonth() {
  const d = new Date(viewDate.value)
  d.setMonth(d.getMonth() + 1)
  viewDate.value = d
}

// 6 weeks × 7 days = 42 cells, Mon-first
const calendarDates = computed<string[]>(() => {
  const y = viewDate.value.getFullYear()
  const m = viewDate.value.getMonth()
  const first = new Date(y, m, 1)
  const startOffset = first.getDay() === 0 ? 6 : first.getDay() - 1
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(y, m, 1 - startOffset + i)
    return localDateStr(d)
  })
})

const today = computed(() => localDateStr(new Date()))

function taskCount(date: string): number {
  const day = planStore.plans[date]
  if (!day) return 0
  return Object.values(day.anchors).reduce((sum, a) => sum + a.tasks.length, 0)
}

// Load plan data for visible dates when month changes
async function loadMonth() {
  const dates = calendarDates.value
  await planStore.fetchPlanRange(dates[0], dates[41])
}

onMounted(loadMonth)
watch(viewDate, loadMonth)

async function onTaskDropped(payload: { taskId: string; date: string; fromAnchorId?: string }) {
  // Pick the first anchor as default when we don't have context
  const defaultAnchorId = anchorStore.anchors[0]?.id ?? ''
  const anchorId = payload.fromAnchorId ?? defaultAnchorId
  await planStore.moveTaskToAnchor({
    taskId: payload.taskId,
    newDate: payload.date,
    anchorId,
  })
}
</script>

<template>
  <div class="bg-[--bg-elev-1] border border-[--border-1] rounded-lg p-2 min-w-[180px] max-w-[220px]">
    <!-- Month navigation -->
    <div class="flex items-center justify-between mb-1.5">
      <button
        data-testid="mini-cal-prev"
        class="text-[--fg-4] hover:text-[--fg-1] text-sm px-1 transition-colors"
        @click="prevMonth"
      >‹</button>
      <span class="text-xs font-medium text-[--fg-2]">{{ monthLabel }}</span>
      <button
        data-testid="mini-cal-next"
        class="text-[--fg-4] hover:text-[--fg-1] text-sm px-1 transition-colors"
        @click="nextMonth"
      >›</button>
    </div>

    <!-- Day-of-week headers (Mon–Sun) -->
    <div class="grid grid-cols-7 mb-0.5">
      <span
        v-for="dow in ['M', 'T', 'W', 'T', 'F', 'S', 'S']"
        :key="dow"
        class="text-[9px] text-center text-[--fg-6] font-medium"
      >{{ dow }}</span>
    </div>

    <!-- Calendar grid — MiniCalendarDay handles drop zone per cell -->
    <div class="grid grid-cols-7 gap-px">
      <MiniCalendarDay
        v-for="date in calendarDates"
        :key="date"
        :date="date"
        :task-count="taskCount(date)"
        :is-today="date === today"
        @task-dropped="onTaskDropped"
      />
    </div>
  </div>
</template>
