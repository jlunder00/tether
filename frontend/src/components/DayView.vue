<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePlanStore } from '../stores/plan'
import { useAnchorStore } from '../stores/anchors'
import AnchorBlock from './AnchorBlock.vue'
import AnchorEditor from './AnchorEditor.vue'
import ContextEditor from './ContextEditor.vue'

const planStore = usePlanStore()
const anchorStore = useAnchorStore()
const tab = ref<'plan' | 'context' | 'anchors'>('plan')

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
        <p class="text-white/40 text-sm">{{ planStore.today }}</p>
      </div>
      <div class="flex gap-2">
        <button @click="tab = 'plan'" :class="tab === 'plan' ? 'bg-white/20' : 'bg-white/5'"
                class="px-4 py-1.5 rounded-lg text-sm">Plan</button>
        <button @click="tab = 'context'" :class="tab === 'context' ? 'bg-white/20' : 'bg-white/5'"
                class="px-4 py-1.5 rounded-lg text-sm">Context</button>
        <button @click="tab = 'anchors'" :class="tab === 'anchors' ? 'bg-white/20' : 'bg-white/5'"
                class="px-4 py-1.5 rounded-lg text-sm">Anchors</button>
      </div>
    </div>

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
  </div>
</template>
