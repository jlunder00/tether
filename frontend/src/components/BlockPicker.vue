<script setup lang="ts">
import { useAnchorStore } from '../stores/anchors'
import type { Anchor } from '../stores/anchors'

defineProps<{ date: string }>()
const emit = defineEmits<{ pick: [anchor: Anchor] }>()
const anchorStore = useAnchorStore()
</script>

<template>
  <div class="absolute z-50 bg-gray-800 border border-white/20 rounded-xl shadow-xl p-3 min-w-[160px]">
    <p class="text-xs text-white/50 mb-2">Move to anchor:</p>
    <button
      v-for="anchor in anchorStore.anchors"
      :key="anchor.id"
      @click="emit('pick', anchor)"
      class="flex items-center gap-2 w-full text-left text-sm px-2 py-1.5 rounded hover:bg-white/10">
      <span class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: anchor.color }" />
      {{ anchor.name }}
    </button>
  </div>
</template>
