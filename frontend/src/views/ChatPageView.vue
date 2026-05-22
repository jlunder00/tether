<script setup lang="ts">
import { ref } from 'vue'
import ContextNodeSidebar from '../components/chat/ContextNodeSidebar.vue'
import ConversationList from '../components/chat/ConversationList.vue'
import ConversationView from '../components/chat/ConversationView.vue'

const activeNodeId = ref<string | null>(null)
</script>

<template>
  <div class="flex h-screen bg-[--bg-1]">
    <!-- Context node sidebar -->
    <div class="w-52 flex-shrink-0 border-r border-[--border-1] overflow-hidden">
      <ContextNodeSidebar v-model:activeNodeId="activeNodeId" />
    </div>
    <!-- Conversation list -->
    <div class="w-72 flex-shrink-0 border-r border-[--border-1] overflow-hidden">
      <ConversationList :activeNodeId="activeNodeId" />
    </div>
    <!-- Conversation view -->
    <div class="flex-1 min-w-0 overflow-hidden">
      <ConversationView />
    </div>
  </div>
</template>
