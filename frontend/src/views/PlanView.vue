<script setup lang="ts">
import { computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import AnchorBlock from '../components/AnchorBlock.vue'
import WeekView from '../components/WeekView.vue'
import MonthView from '../components/MonthView.vue'

const props = defineProps<{ view: string; date?: string }>()
const router = useRouter()
const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const milestoneStore = useMilestoneStore()

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
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <div class="flex items-center gap-2 mt-1">
          <template v-if="props.view === 'day'">
            <button @click="prevDay"
                    class="text-white/40 hover:text-white text-lg leading-none px-1">‹</button>
            <span class="text-sm font-medium min-w-[90px] text-center">{{ displayDate }}</span>
            <button @click="nextDay"
                    class="text-white/40 hover:text-white text-lg leading-none px-1">›</button>
            <button v-if="!isToday" @click="goToday"
                    class="text-xs text-white/40 hover:text-white ml-1 border border-white/20 rounded px-2 py-0.5">
              Today
            </button>
          </template>
          <template v-else>
            <span class="text-sm text-white/50">{{ props.view === 'week' ? 'Week' : 'Month' }} view</span>
          </template>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- Zoom controls -->
        <div class="flex gap-1 bg-white/5 rounded-lg p-0.5">
          <router-link :to="'/plan/day/' + activeDate"
                       :class="props.view === 'day' ? 'bg-white/20 text-white' : 'text-white/40 hover:text-white/70'"
                       class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            D
          </router-link>
          <router-link :to="'/plan/week/' + activeDate"
                       :class="props.view === 'week' ? 'bg-white/20 text-white' : 'text-white/40 hover:text-white/70'"
                       class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            W
          </router-link>
          <router-link :to="'/plan/month/' + activeDate"
                       :class="props.view === 'month' ? 'bg-white/20 text-white' : 'text-white/40 hover:text-white/70'"
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

    <!-- Day view -->
    <template v-else>
      <div v-if="planStore.loading" class="text-white/40">Loading...</div>
      <div v-else class="flex flex-col gap-2">
        <AnchorBlock
          v-for="anchor in anchorStore.anchors"
          :key="anchor.id"
          :anchor-id="anchor.id"
          :anchor-name="anchor.name"
          :time="anchor.time"
          :color="anchor.color" />
      </div>
    </template>

    <!-- Child route detail panels -->
    <router-view />
  </div>
</template>
