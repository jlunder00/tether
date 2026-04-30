<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { usePlanStore } from '../stores/plan'
import DayColumn from './DayColumn.vue'

const planStore = usePlanStore()

function getMonday(dateStr: string): Date {
  const d = new Date(dateStr + 'T12:00:00')
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return d
}

function dateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const weekStart = ref(getMonday(planStore.activeDate))

const weekDates = computed<string[]>(() => {
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(weekStart.value)
    d.setDate(d.getDate() + i)
    return dateStr(d)
  })
})

const weekLabel = computed(() => {
  const start = weekDates.value[0]
  const end = weekDates.value[6]
  const s = new Date(start + 'T12:00:00')
  const e = new Date(end + 'T12:00:00')
  return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} – ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
})

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

async function loadWeek() {
  await planStore.fetchPlanRange(weekDates.value[0], weekDates.value[6])
}

onMounted(loadWeek)
watch(weekStart, loadWeek)
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-4">
      <button @click="prevWeek" class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1">‹</button>
      <span class="text-sm font-medium min-w-[160px] text-center">{{ weekLabel }}</span>
      <button @click="nextWeek" class="text-[--fg-4] hover:text-[--fg-1] text-lg px-1">›</button>
    </div>
    <div class="grid grid-cols-7 gap-2">
      <DayColumn
        v-for="date in weekDates"
        :key="date"
        :date="date"
        :is-today="date === planStore.today" />
    </div>
  </div>
</template>
