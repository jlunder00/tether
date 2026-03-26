<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { usePlanStore } from '../stores/plan'
import AnchorBlock from './AnchorBlock.vue'
import ContextEditor from './ContextEditor.vue'

const store = usePlanStore()
const tab = ref<'plan' | 'context'>('plan')

const ANCHOR_META: Record<string, { name: string; time: string; color: string }> = {
  launch_pad:        { name: 'Launch Pad',     time: '7:00 AM',  color: '#5b8dee' },
  grind_am:          { name: 'The Grind',      time: '8:00 AM',  color: '#e05c5c' },
  rest_am:           { name: 'Rest / Reset',   time: '10:00 AM', color: '#4caf8c' },
  deep_work:         { name: 'Deep Work',      time: '10:30 AM', color: '#7c6af7' },
  rest_lunch:        { name: 'Rest / Reset',   time: '12:30 PM', color: '#4caf8c' },
  grind_pm:          { name: 'The Grind',      time: '1:30 PM',  color: '#e05c5c' },
  flex_time:         { name: 'Flex Time',      time: '3:00 PM',  color: '#e8a838' },
  wind_down_work:    { name: 'Wind Down',      time: '4:00 PM',  color: '#888888' },
  leisure:           { name: 'Rest / Leisure', time: '5:00 PM',  color: '#4caf8c' },
  wind_down_evening: { name: 'Wind Down',      time: '9:00 PM',  color: '#3a3a5c' },
}

onMounted(() => { store.fetchPlan(); store.connectWebSocket() })
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold">Tether</h1>
        <p class="text-white/40 text-sm">{{ store.today }}</p>
      </div>
      <div class="flex gap-2">
        <button @click="tab = 'plan'" :class="tab === 'plan' ? 'bg-white/20' : 'bg-white/5'"
                class="px-4 py-1.5 rounded-lg text-sm">Plan</button>
        <button @click="tab = 'context'" :class="tab === 'context' ? 'bg-white/20' : 'bg-white/5'"
                class="px-4 py-1.5 rounded-lg text-sm">Context</button>
      </div>
    </div>

    <div v-if="tab === 'plan'">
      <div v-if="store.loading" class="text-white/40">Loading...</div>
      <div v-else class="flex flex-col gap-2">
        <template v-for="(meta, id) in ANCHOR_META" :key="id">
          <AnchorBlock
            :anchor-id="id" :anchor-name="meta.name"
            :time="meta.time" :color="meta.color" />
        </template>
      </div>
    </div>

    <ContextEditor v-else />
  </div>
</template>
