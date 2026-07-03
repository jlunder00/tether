<script setup lang="ts">
import { computed } from 'vue'
import { useChatStore } from '../stores/chat'
import type { StatusPhase } from '../types/chat'

const PHASE_LABELS: Record<StatusPhase, string> = {
  classifier: 'Classifying…',
  main_reasoning: 'Thinking…',
  tool_call: 'Using tools…',
  summarization: 'Summarizing…',
}

const chatStore = useChatStore()

const phaseLabel = computed(() =>
  chatStore.currentPhase ? PHASE_LABELS[chatStore.currentPhase] : null
)
</script>

<template>
  <div v-if="chatStore.currentPhase" class="flex flex-col items-center gap-0.5 py-1">
    <span class="text-xs text-[--fg-4] animate-pulse">{{ phaseLabel }}</span>
    <span v-if="chatStore.statusMessage" class="text-xs text-[--fg-5]">
      {{ chatStore.statusMessage }}
    </span>
  </div>
</template>
