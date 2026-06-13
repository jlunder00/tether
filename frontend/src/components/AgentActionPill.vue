<script setup lang="ts">
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
</script>

<template>
  <div v-if="chatStore.activeActions.size > 0" class="flex flex-col gap-1 px-3 py-2">
    <div
      v-for="[id, action] in chatStore.activeActions"
      :key="id"
      data-pill
      class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-[--bg-elev-2] text-xs text-[--fg-3] w-fit"
      :class="action.status === 'complete' ? 'opacity-40' : 'opacity-100'"
    >
      <!-- Spinner for starting/running -->
      <span
        v-if="action.status !== 'complete'"
        :data-status="action.status"
        class="inline-block w-3 h-3 border-2 border-[--fg-4] border-t-[--accent] rounded-full animate-spin"
      />
      <!-- Checkmark for complete -->
      <span
        v-else
        :data-status="action.status"
        class="inline-flex items-center justify-center w-3 h-3 text-[--status-done-fg]"
      >
        <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" class="w-3 h-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="M2 6l3 3 5-5" />
        </svg>
      </span>
      <span>{{ action.friendly_text }}</span>
    </div>
  </div>
</template>
