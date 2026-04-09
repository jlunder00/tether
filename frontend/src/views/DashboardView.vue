<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { api } from '../lib/api'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const milestoneStore = useMilestoneStore()
const botStatus = ref('unknown')

onMounted(async () => {
  planStore.fetchPlan()
  anchorStore.fetchAnchors()
  milestoneStore.fetchAll()
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
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="flex items-center gap-4 mb-6">
      <h1 class="text-2xl font-bold">Dashboard</h1>
      <div class="flex items-center gap-2 text-sm">
        <span class="w-2 h-2 rounded-full"
              :class="botStatus === 'ok' ? 'bg-green-400' : botStatus === 'stale' ? 'bg-yellow-400' : 'bg-red-400'" />
        <span class="text-white/50">Bot {{ botStatus }}</span>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- Now Box -->
      <div class="bg-white/5 border border-white/10 rounded-xl p-4">
        <div class="flex items-center gap-2 mb-3">
          <div v-if="currentAnchor" class="w-3 h-3 rounded-full" :style="{ background: currentAnchor.color }" />
          <h2 class="font-semibold text-lg">{{ currentAnchor?.name ?? 'No active block' }}</h2>
          <span class="text-white/40 text-sm ml-auto">{{ currentAnchor?.time }}</span>
        </div>
        <ul class="flex flex-col gap-1.5">
          <li v-for="task in currentTasks" :key="task.id" class="flex items-center gap-2 text-sm">
            <span class="w-2 h-2 rounded-full flex-shrink-0"
                  :class="task.status === 'done' ? 'bg-green-400' : task.status === 'in_progress' ? 'bg-blue-400' : 'bg-white/20'" />
            <span :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
          </li>
          <li v-if="!currentTasks.length" class="text-white/30 text-sm">No tasks</li>
        </ul>
      </div>

      <!-- Today Box -->
      <div class="bg-white/5 border border-white/10 rounded-xl p-4">
        <h2 class="font-semibold text-lg mb-3">Today</h2>
        <ul class="flex flex-col gap-2">
          <li v-for="s in dayStats" :key="s.anchor.id"
              class="flex items-center gap-2 text-sm"
              :class="currentAnchor?.id === s.anchor.id ? 'text-white' : 'text-white/40'">
            <div class="w-2 h-2 rounded-full flex-shrink-0" :style="{ background: s.anchor.color }" />
            <span class="flex-1">{{ s.anchor.name }}</span>
            <span class="text-xs">{{ s.done }}/{{ s.total }}</span>
          </li>
        </ul>
      </div>

      <!-- This Week Box -->
      <div class="bg-white/5 border border-white/10 rounded-xl p-4">
        <h2 class="font-semibold text-lg mb-3">This Week</h2>
        <p class="text-white/30 text-sm">Coming soon</p>
      </div>
    </div>

    <router-view />
  </div>
</template>
