<script setup lang="ts">
import ConversationList from '../components/chat/ConversationList.vue'
import ConversationView from '../components/chat/ConversationView.vue'
</script>

<template>
  <div class="flex h-screen bg-[--bg-1]">
    <!-- Left pane: conversation list -->
    <div class="w-80 flex-shrink-0 border-r border-[--border-1] overflow-hidden">
      <ConversationList />
    </div>

    <!-- Right pane: conversation view -->
    <div class="flex-1 min-w-0 overflow-hidden">
      <ConversationView />
    </div>
  </div>
</template>
