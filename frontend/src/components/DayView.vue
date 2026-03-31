<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import AnchorBlock from './AnchorBlock.vue'
import AnchorEditor from './AnchorEditor.vue'
import ContextEditor from './ContextEditor.vue'
import WeekView from './WeekView.vue'
import MonthView from './MonthView.vue'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const tab = ref<'plan' | 'context' | 'anchors'>('plan')
const zoom = ref<'d' | 'w' | 'm'>('d')

const isToday = computed(() => planStore.activeDate === planStore.today)

const displayDate = computed(() => {
  const diff = Math.round(
    (new Date(planStore.activeDate + 'T12:00:00').getTime() -
     new Date(planStore.today + 'T12:00:00').getTime()) / 86400000
  )
  if (diff === 0) return 'Today'
  if (diff === 1) return 'Tomorrow'
  if (diff === -1) return 'Yesterday'
  const d = new Date(planStore.activeDate + 'T12:00:00')
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
})

onMounted(() => {
  planStore.fetchPlan()
  planStore.connectWebSocket()
  anchorStore.fetchAnchors()
})
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold">Tether</h1>
        <div class="flex items-center gap-2 mt-1">
          <template v-if="zoom === 'd'">
            <button @click="planStore.goToPrevDay()"
                    class="text-white/40 hover:text-white text-lg leading-none px-1">‹</button>
            <span class="text-sm font-medium min-w-[90px] text-center">{{ displayDate }}</span>
            <button @click="planStore.goToNextDay()"
                    class="text-white/40 hover:text-white text-lg leading-none px-1">›</button>
            <button v-if="!isToday" @click="planStore.goToToday()"
                    class="text-xs text-white/40 hover:text-white ml-1 border border-white/20 rounded px-2 py-0.5">
              Today
            </button>
          </template>
          <template v-else>
            <span class="text-sm text-white/50">{{ zoom === 'w' ? 'Week' : 'Month' }} view</span>
          </template>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- Zoom controls -->
        <div class="flex gap-1 bg-white/5 rounded-lg p-0.5">
          <button v-for="z in (['d','w','m'] as const)" :key="z"
                  @click="zoom = z"
                  :class="zoom === z ? 'bg-white/20 text-white' : 'text-white/40 hover:text-white/70'"
                  class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            {{ z }}
          </button>
        </div>
        <!-- Tab controls -->
        <div class="flex gap-2">
          <button @click="tab = 'plan'" :class="tab === 'plan' ? 'bg-white/20' : 'bg-white/5'"
                  class="px-4 py-1.5 rounded-lg text-sm">Plan</button>
          <button @click="tab = 'context'" :class="tab === 'context' ? 'bg-white/20' : 'bg-white/5'"
                  class="px-4 py-1.5 rounded-lg text-sm">Context</button>
          <button @click="tab = 'anchors'" :class="tab === 'anchors' ? 'bg-white/20' : 'bg-white/5'"
                  class="px-4 py-1.5 rounded-lg text-sm">Anchors</button>
        </div>
      </div>
    </div>

    <!-- Week view -->
    <WeekView v-if="zoom === 'w'" />

    <!-- Month view -->
    <MonthView v-else-if="zoom === 'm'" />

    <!-- Day view -->
    <template v-else>
      <div v-if="tab === 'plan'">
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
      </div>

      <ContextEditor v-else-if="tab === 'context'" />

      <div v-else class="flex flex-col gap-3">
        <AnchorEditor
          v-for="anchor in anchorStore.anchors"
          :key="anchor.id"
          :anchor="anchor"
          @save="anchorStore.updateAnchor($event)" />
      </div>
    </template>
  </div>
</template>
