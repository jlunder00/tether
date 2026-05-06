<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { api } from '../lib/api'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { useEventStore } from '../stores/events'
import TaskCard from '../components/TaskCard.vue'
import AnchorFocusWidget from '../components/AnchorFocusWidget.vue'
import { textOnColor } from '../composables/useTextOnColor'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const milestoneStore = useMilestoneStore()
const eventStore = useEventStore()
const botStatus = ref('unknown')

function localToday(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

onMounted(async () => {
  planStore.fetchPlan()
  anchorStore.fetchAnchors()
  milestoneStore.fetchAll()
  const today = localToday()
  eventStore.fetchEvents(today, today)
  try {
    const resp = await api('/api/bot/health')
    if (resp.ok) {
      const data = await resp.json()
      botStatus.value = data.status
    }
  } catch { /* ignore */ }
})

const now = ref(new Date())
setInterval(() => { now.value = new Date() }, 60_000)

const currentAnchor = computed(() => {
  const sorted = [...anchorStore.anchors].sort((a, b) => a.time.localeCompare(b.time))
  let active = sorted[0]
  for (const a of sorted) {
    const [h, m] = a.time.split(':').map(Number)
    const anchorTime = new Date()
    anchorTime.setHours(h, m, 0, 0)
    if (now.value >= anchorTime) active = a
    else break
  }
  return active
})

const currentTasks = computed(() => {
  if (!currentAnchor.value || !planStore.plan) return []
  return planStore.plan.anchors[currentAnchor.value.id]?.tasks ?? []
})

async function onAddTaskToNow() {
  if (!currentAnchor.value) return
  const today = localToday()
  try {
    const resp = await api('/api/tasks/unscheduled', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: 'New task', date: today, anchor_id: currentAnchor.value.id }),
    })
    if (!resp.ok) throw new Error(`${resp.status}`)
    await planStore.fetchPlan(today)
  } catch (e) {
    console.error('Failed to create task:', e)
  }
}

const allDayEventsToday = computed(() => {
  return eventStore.events.filter(ev => ev.is_all_day === true && ev.start_time.startsWith(localToday()))
})

const dayStats = computed(() => {
  if (!planStore.plan) return []
  return anchorStore.anchors.map(a => {
    const tasks = planStore.plan!.anchors[a.id]?.tasks ?? []
    const done = tasks.filter(t => t.status === 'done').length
    return { anchor: a, total: tasks.length, done }
  })
})
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="flex items-center gap-4 mb-6">
      <h1 class="text-2xl font-bold">Dashboard</h1>
      <div class="flex items-center gap-2 text-sm">
        <span class="w-2 h-2 rounded-full"
              :class="botStatus === 'ok' ? 'bg-green-400' : botStatus === 'stale' ? 'bg-yellow-400' : 'bg-red-400'" />
        <span class="text-[--fg-3]">Bot {{ botStatus }}</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- Now Box -->
      <div class="bg-[--bg-elev-2] border border-[--border-1] rounded-xl p-4">
        <div class="mb-3">
          <AnchorFocusWidget />
        </div>
        <div v-if="allDayEventsToday.length" class="flex flex-wrap gap-1 mb-2">
          <div v-for="ev in allDayEventsToday" :key="ev.id"
               data-testid="all-day-event-chip"
               class="text-xs px-2 py-0.5 rounded font-medium"
               :style="{ backgroundColor: ev.color ?? '#6366f1', color: textOnColor(ev.color ?? '#6366f1') }">
            {{ ev.title }}
          </div>
        </div>
        <ul class="flex flex-col gap-1.5">
          <TaskCard v-for="task in currentTasks" :key="task.id"
            :task="task" :editable="false" :show-remove="false" :show-detail-link="false" :compact="true" />
          <li v-if="!currentTasks.length" class="text-[--fg-5] text-sm">No tasks</li>
        </ul>
        <button v-if="currentAnchor" type="button" @click="onAddTaskToNow"
                class="mt-2 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-left">
          + Add task
        </button>
      </div>

      <!-- Today Box -->
      <div class="bg-[--bg-elev-2] border border-[--border-1] rounded-xl p-4">
        <h2 class="font-semibold text-lg mb-3">Today</h2>
        <ul class="flex flex-col gap-2">
          <li v-for="s in dayStats" :key="s.anchor.id"
              class="flex items-center gap-2 text-sm"
              :class="currentAnchor?.id === s.anchor.id ? 'text-[--fg-1]' : 'text-[--fg-4]'">
            <div class="w-2 h-2 rounded-full flex-shrink-0" :style="{ background: s.anchor.color }" />
            <span class="flex-1">{{ s.anchor.name }}</span>
            <span class="text-xs">{{ s.done }}/{{ s.total }}</span>
          </li>
        </ul>
      </div>

    </div>
  </div>
</template>
