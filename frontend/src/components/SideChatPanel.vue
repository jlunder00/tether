<script setup lang="ts">
import FolderCenterPanel from './chat/FolderCenterPanel.vue'
import ConversationView from './chat/ConversationView.vue'

const emit = defineEmits<{ close: [] }>()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
</script>

<template>
  <div class="flex flex-col h-full" @keydown="onKeydown">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-[--border-1] flex-shrink-0">
      <span class="font-semibold text-sm text-[--fg-1]">Chat</span>
      <button
        class="text-[--fg-4] hover:text-[--fg-1] transition-colors p-1"
        aria-label="Close chat panel"
        type="button"
        @click="emit('close')"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Content: compact split (conversation list + view side by side) -->
    <div class="flex flex-1 overflow-hidden">
      <!-- Narrow conversation list -->
      <div class="w-40 flex-shrink-0 border-r border-[--border-1] overflow-hidden">
        <FolderCenterPanel :node-id="null" />
      </div>

      <!-- Conversation view -->
      <div class="flex-1 min-w-0 overflow-hidden">
        <ConversationView />
      </div>
    </div>
  </div>
</template>
