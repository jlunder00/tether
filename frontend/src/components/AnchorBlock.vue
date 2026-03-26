<script setup lang="ts">
import { computed } from 'vue'
import TaskList from './TaskList.vue'
import { usePlanStore } from '../stores/plan'

const props = defineProps<{ anchorId: string; anchorName: string; time: string; color: string }>()
const store = usePlanStore()
const anchorPlan = computed(() => store.plan?.anchors[props.anchorId])

async function onUpdate(tasks: string[]) {
  await store.updateAnchorTasks(props.anchorId, tasks, anchorPlan.value?.notes ?? '')
}
</script>

<template>
  <div class="flex rounded-xl overflow-hidden" v-if="anchorPlan">
    <div class="flex flex-col justify-center px-4 py-3 min-w-[110px] text-white"
         :style="{ background: color }">
      <span class="text-xs opacity-75">{{ time }}</span>
      <span class="font-bold text-sm mt-0.5">{{ anchorName }}</span>
    </div>
    <div class="flex-1 bg-white/5 border border-white/10 border-l-0 px-4 py-3">
      <TaskList :tasks="anchorPlan.tasks" @update="onUpdate" />
    </div>
  </div>
</template>
