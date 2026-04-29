<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { usePlanStore } from '../stores/plan'
import BlockPicker from './BlockPicker.vue'
import type { Anchor } from '../stores/anchors'

const planStore = usePlanStore()

function dateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const viewDate = ref(new Date(planStore.activeDate + 'T12:00:00'))

const monthLabel = computed(() =>
  viewDate.value.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
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

// Build calendar grid (always 6 weeks × 7 days, Mon-first)
const calendarDates = computed<string[]>(() => {
  const y = viewDate.value.getFullYear()
  const m = viewDate.value.getMonth()
  const first = new Date(y, m, 1)
  const startOffset = first.getDay() === 0 ? 6 : first.getDay() - 1
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(y, m, 1 - startOffset + i)
    return dateStr(d)
  })
})

const currentMonth = computed(() => viewDate.value.getMonth())

function isCurrentMonth(date: string) {
  return new Date(date + 'T12:00:00').getMonth() === currentMonth.value
}

function taskCounts(date: string) {
  const day = planStore.plans[date]
  if (!day) return { total: 0, done: 0 }
  const anchors = Object.values(day.anchors)
  return {
    total: anchors.reduce((n, a) => n + a.tasks.length, 0),
    done: anchors.reduce((n, a) => n + a.tasks.filter(t => t.status === 'done').length, 0),
  }
}

// Drag-to-month
const draggedTask = ref<{ id: string; fromDate: string; fromAnchor: string } | null>(null)
const pickerDate = ref<string | null>(null)

function onDragOverCell(date: string) {
  if (!draggedTask.value) return
  pickerDate.value = date
}

function onPickAnchor(anchor: Anchor) {
  if (!draggedTask.value || !pickerDate.value) return
  planStore.moveTask(
    draggedTask.value.id,
    draggedTask.value.fromDate,
    draggedTask.value.fromAnchor,
    pickerDate.value,
    anchor.id,
  )
  draggedTask.value = null
  pickerDate.value = null
}

function loadMonth() {
  const dates = calendarDates.value
  planStore.fetchPlanRange(dates[0], dates[dates.length - 1])
}

onMounted(loadMonth)
watch(viewDate, loadMonth)
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-4">
      <button @click="prevMonth" class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1">‹</button>
      <span class="text-sm font-medium min-w-[140px] text-center text-[--fg-1]">{{ monthLabel }}</span>
      <button @click="nextMonth" class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1">›</button>
    </div>

    <!-- Day-of-week headers -->
    <div class="grid grid-cols-7 gap-1 mb-1">
      <div v-for="d in ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']" :key="d"
           class="text-center text-xs text-[--fg-5] py-1">{{ d }}</div>
    </div>

    <!-- Calendar grid -->
    <div class="grid grid-cols-7 gap-1">
      <div
        v-for="date in calendarDates" :key="date"
        class="relative min-h-[64px] rounded-lg p-1.5 cursor-pointer transition-colors"
        :class="[
          isCurrentMonth(date) ? 'bg-[--bg-elev-2] hover:bg-[--bg-elev-3]' : 'bg-[--bg-elev-1] opacity-40',
          date === planStore.today ? 'ring-1 ring-[--accent]' : '',
        ]"
        @click="planStore.fetchPlan(date)"
        @dragover.prevent="onDragOverCell(date)"
        @drop.prevent>
        <div class="text-xs text-[--fg-3] mb-1">
          {{ new Date(date + 'T12:00:00').getDate() }}
        </div>
        <template v-if="taskCounts(date).total > 0">
          <div class="text-xs text-[--fg-2]">
            {{ taskCounts(date).done }}/{{ taskCounts(date).total }}
          </div>
          <div class="mt-1 h-1 bg-[--bg-elev-3] rounded-full overflow-hidden">
            <div class="h-full bg-[--status-done-fg] rounded-full"
                 :style="{ width: `${(taskCounts(date).done / taskCounts(date).total) * 100}%` }" />
          </div>
        </template>

        <BlockPicker
          v-if="pickerDate === date && draggedTask"
          :date="date"
          @pick="onPickAnchor" />
      </div>
    </div>
  </div>
</template>
