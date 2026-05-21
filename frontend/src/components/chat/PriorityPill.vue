<script setup lang="ts">
import type { ConversationPriority } from '../../types/conversations'

const props = withDefaults(defineProps<{
  priority: ConversationPriority
  clickable?: boolean
}>(), {
  clickable: false,
})

const emit = defineEmits<{
  change: [priority: ConversationPriority]
}>()

const PRIORITY_NEXT: Record<ConversationPriority, ConversationPriority> = {
  low: 'normal',
  normal: 'high',
  high: 'urgent',
  urgent: 'low',
}

const COLOR_MAP: Record<ConversationPriority, string> = {
  low: 'bg-[--fg-5] text-[--bg-1]',
  normal: 'bg-blue-500 text-white',
  high: 'bg-orange-500 text-white',
  urgent: 'bg-red-500 text-white',
}

function onClick() {
  if (!props.clickable) return
  emit('change', PRIORITY_NEXT[props.priority])
}
</script>

<template>
  <span
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium select-none"
    :class="[COLOR_MAP[priority], clickable ? 'cursor-pointer hover:opacity-80' : '']"
    @click="onClick"
  >
    {{ priority }}
  </span>
</template>
