<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore, computeAnchorStates } from '../stores/anchors'
import { useAuthStore } from '../stores/auth'
import AnchorBlock from './AnchorBlock.vue'
import AnchorEditor from './AnchorEditor.vue'
import ContextEditor from './ContextEditor.vue'
import WeekView from './WeekView.vue'
import MonthView from './MonthView.vue'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const authStore = useAuthStore()
const tab = ref<'plan' | 'context' | 'anchors'>('plan')
const zoom = ref<'d' | 'w' | 'm'>('d')

// Reactive clock for anchor state updates (refreshes every minute)
const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | null = null

const anchorStates = computed(() => computeAnchorStates(anchorStore.anchors, now.value))

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
  clockTimer = setInterval(() => { now.value = new Date() }, 60_000)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold">Tether</h1>
        <div class="flex items-center gap-2 mt-1">
          <template v-if="zoom === 'd'">
            <button @click="planStore.goToPrevDay()"
                    class="text-[--fg-4] hover:text-[--fg-1] text-lg leading-none px-1">‹</button>
            <span class="text-sm font-medium min-w-[90px] text-center">{{ displayDate }}</span>
            <button @click="planStore.goToNextDay()"
                    class="text-[--fg-4] hover:text-[--fg-1] text-lg leading-none px-1">›</button>
            <button v-if="!isToday" @click="planStore.goToToday()"
                    class="text-xs text-[--fg-4] hover:text-[--fg-1] ml-1 border border-[--border-1] rounded px-2 py-0.5">
              Today
            </button>
          </template>
          <template v-else>
            <span class="text-sm text-[--fg-3]">{{ zoom === 'w' ? 'Week' : 'Month' }} view</span>
          </template>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <!-- Zoom controls -->
        <div class="flex gap-1 bg-[--bg-elev-1] rounded-lg p-0.5">
          <button v-for="z in (['d','w','m'] as const)" :key="z"
                  @click="zoom = z"
                  :class="zoom === z ? 'bg-[--bg-elev-2] text-[--fg-1]' : 'text-[--fg-4] hover:text-[--fg-2]'"
                  class="px-2.5 py-1 rounded text-xs uppercase font-medium transition-colors">
            {{ z }}
          </button>
        </div>
        <!-- Tab controls -->
        <div class="flex gap-2">
          <button @click="tab = 'plan'" :class="tab === 'plan' ? 'bg-[--bg-elev-2]' : 'bg-[--bg-elev-1]'"
                  class="px-4 py-1.5 rounded-lg text-sm">Plan</button>
          <button @click="tab = 'context'" :class="tab === 'context' ? 'bg-[--bg-elev-2]' : 'bg-[--bg-elev-1]'"
                  class="px-4 py-1.5 rounded-lg text-sm">Context</button>
          <button @click="tab = 'anchors'" :class="tab === 'anchors' ? 'bg-[--bg-elev-2]' : 'bg-[--bg-elev-1]'"
                  class="px-4 py-1.5 rounded-lg text-sm">Anchors</button>
        </div>
        <!-- User nav -->
        <div class="flex items-center gap-2 ml-1">
          <router-link v-if="authStore.user?.is_admin" to="/admin"
                       class="text-xs text-[--fg-4] hover:text-[--fg-2] border border-[--border-soft] rounded px-2 py-1 transition-colors">
            Admin
          </router-link>
          <router-link to="/settings"
                       class="text-[--fg-4] hover:text-[--fg-2] transition-colors"
                       title="Settings">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </router-link>
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
        <div v-if="planStore.loading" class="text-[--fg-4]">Loading...</div>
        <div v-else class="flex flex-col">
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
