<script setup lang="ts">
import { ref, computed } from 'vue'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import AnchorBlock from './AnchorBlock.vue'

const props = defineProps<{ date: string; isToday: boolean }>()
const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const expanded = ref(false)

const dayPlan = computed(() => planStore.plans[props.date])
const totalTasks = computed(() => {
  if (!dayPlan.value) return 0
  return Object.values(dayPlan.value.anchors).reduce((n, a) => n + a.tasks.length, 0)
})
const doneTasks = computed(() => {
  if (!dayPlan.value) return 0
  return Object.values(dayPlan.value.anchors)
    .reduce((n, a) => n + a.tasks.filter(t => t.status === 'done').length, 0)
})

const label = computed(() => {
  const d = new Date(props.date + 'T12:00:00')
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })
})
</script>

<template>
  <div class="flex flex-col min-w-0">
    <button
      @click="expanded = !expanded"
      class="text-center py-2 px-1 rounded-t-lg text-xs font-medium"
      :class="isToday ? 'bg-white/20 text-white' : 'bg-white/5 text-white/60 hover:bg-white/10'">
      {{ label }}
      <span class="block text-white/40 text-xs font-normal mt-0.5">
        {{ doneTasks }}/{{ totalTasks }} ✓
      </span>
    </button>

    <div v-if="expanded" class="flex flex-col gap-2 mt-2">
      <AnchorBlock
        v-for="anchor in anchorStore.anchors"
        :key="anchor.id"
        :anchor-id="anchor.id"
        :anchor-name="anchor.name"
        :time="anchor.time"
        :color="anchor.color"
        :date="date" />
    </div>
    <div v-else class="flex flex-col gap-1 mt-1">
      <div
        v-for="anchor in anchorStore.anchors"
        :key="anchor.id"
        class="rounded px-2 py-1 text-xs text-white/60 truncate"
        :style="{ background: anchor.color + '33' }">
        {{ anchor.name }}
      </div>
    </div>
  </div>
</template>
