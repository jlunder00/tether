<script setup lang="ts">
import type { ConversationState } from '../../types/conversations'

const props = withDefaults(defineProps<{
  state: ConversationState
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  change: [state: ConversationState]
}>()

function onClick() {
  if (props.loading) return
  emit('change', props.state === 'open' ? 'closed' : 'open')
}
</script>

<template>
  <button
    type="button"
    class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium select-none transition-colors"
    :class="[
      state === 'open'
        ? 'bg-green-500 text-white hover:bg-green-600'
        : 'bg-[--fg-5] text-[--bg-1] hover:bg-[--fg-4]',
      loading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
    ]"
    :disabled="loading"
    @click="onClick"
  >
    <span :class="state === 'closed' ? 'line-through' : ''">{{ state }}</span>
  </button>
</template>
