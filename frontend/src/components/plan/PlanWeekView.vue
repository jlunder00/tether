<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { usePlanStore } from '../../stores/plan'
import { useAnchorStore } from '../../stores/anchors'
import { useDragEdgeScroll } from '../../composables/useDragEdgeScroll'
import PlanWeekCell from './PlanWeekCell.vue'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()

// ── Week navigation ────────────────────────────────────────────────────────────
function getMonday(dateStr: string): Date {
  const d = new Date(dateStr + 'T12:00:00')
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return d
}

function localDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const weekStart = ref(getMonday(planStore.activeDate))

const weekDates = computed<string[]>(() =>
  Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    return localDateStr(d)
  }),
)

const weekLabel = computed(() => {
  const s = new Date(weekDates.value[0] + 'T12:00:00')
  const e = new Date(weekDates.value[6] + 'T12:00:00')
  return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
})

// Day-of-week headers (Mon–Sun) with date numbers
const dayHeaders = computed(() =>
  weekDates.value.map(dateStr => {
    const d = new Date(dateStr + 'T12:00:00')
    return {
      dateStr,
      label: d.toLocaleDateString(undefined, { weekday: 'short' }),
      dayNum: d.getDate(),
      isToday: dateStr === planStore.today,
    }
  }),
)

function prevWeek() {
  const d = new Date(weekStart.value)
  d.setDate(d.getDate() - 7)
  weekStart.value = d
}

function nextWeek() {
  const d = new Date(weekStart.value)
  d.setDate(d.getDate() + 7)
  weekStart.value = d
}

// ── Data loading ───────────────────────────────────────────────────────────────
async function loadWeek() {
  await Promise.all(weekDates.value.map(d => planStore.fetchPlan(d)))
}

onMounted(() => {
  anchorStore.fetchAnchors()
  loadWeek()
})

watch(weekStart, loadWeek)

// ── Cell data accessor ─────────────────────────────────────────────────────────
function cellTasks(anchorId: string, dateStr: string) {
  return planStore.plans[dateStr]?.anchors[anchorId]?.tasks ?? []
}

// ── Edge-scroll wiring ─────────────────────────────────────────────────────────
const gridRef = ref<HTMLElement | null>(null)

const { onDragOver: edgeDragOver, onDragLeave: edgeDragLeave, onDragEnd: edgeDragEnd } =
  useDragEdgeScroll(gridRef, (direction) => {
    if (direction === 'prev') prevWeek()
    else nextWeek()
  })
</script>

<template>
  <div>
    <!-- Week navigation header -->
    <div class="flex items-center gap-2 mb-3">
      <button
        data-testid="week-prev"
        class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1 transition-colors"
        @click="prevWeek"
      >
        ‹
      </button>
      <span class="text-sm font-medium min-w-[160px] text-center">{{ weekLabel }}</span>
      <button
        data-testid="week-next"
        class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1 transition-colors"
        @click="nextWeek"
      >
        ›
      </button>
    </div>

    <!-- Grid: anchor labels × day columns -->
    <div
      ref="gridRef"
      data-testid="week-plan-grid"
      class="overflow-x-auto"
      @dragover="edgeDragOver"
      @dragleave="edgeDragLeave"
      @dragend="edgeDragEnd"
    >
      <div
        class="grid min-w-[600px]"
        :style="{ gridTemplateColumns: `120px repeat(7, 1fr)` }"
      >
        <!-- Header row: blank corner + day headers -->
        <div class="sticky top-0 z-10 bg-[--bg-canvas] border-b border-[--border-1] h-10" />
        <div
          v-for="day in dayHeaders"
          :key="day.dateStr"
          class="sticky top-0 z-10 bg-[--bg-canvas] border-b border-[--border-1] border-l border-[--border-soft] px-1 py-1.5 text-center"
        >
          <div
            class="text-xs font-medium"
            :class="day.isToday ? 'text-[--accent]' : 'text-[--fg-3]'"
          >
            {{ day.label }}
          </div>
          <div
            class="text-sm font-semibold"
            :class="day.isToday ? 'text-[--accent]' : 'text-[--fg-1]'"
          >
            {{ day.dayNum }}
          </div>
        </div>

        <!-- Anchor rows -->
        <template v-for="anchor in anchorStore.anchors" :key="anchor.id">
          <!-- Anchor name label -->
          <div
            class="px-2 py-2 border-b border-[--border-soft] flex items-start gap-1.5"
            :style="{ borderLeft: `3px solid ${anchor.color}` }"
          >
            <div>
              <div class="text-xs font-medium text-[--fg-2] truncate leading-tight">
                {{ anchor.name }}
              </div>
              <div class="text-[10px] text-[--fg-5]">{{ anchor.time }}</div>
            </div>
          </div>

          <!-- Day cells for this anchor -->
          <div
            v-for="dateStr in weekDates"
            :key="dateStr"
            class="border-b border-[--border-soft] border-l border-[--border-soft] p-0.5"
          >
            <PlanWeekCell
              :date="dateStr"
              :anchor-id="anchor.id"
              :anchor-name="anchor.name"
              :tasks="cellTasks(anchor.id, dateStr)"
            />
          </div>
        </template>

        <!-- Empty state when no anchors loaded -->
        <div
          v-if="!anchorStore.anchors.length"
          class="col-span-8 text-center text-sm text-[--fg-4] py-8"
        >
          No anchors configured
        </div>
      </div>
    </div>
  </div>
</template>
