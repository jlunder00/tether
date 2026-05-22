<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useConversationsStore } from '../../stores/conversations'
import type { ConversationDetail } from '../../types/conversations'
import PriorityPill from './PriorityPill.vue'
import NewConversationModal from './NewConversationModal.vue'

const props = withDefaults(defineProps<{
  activeNodeId?: string | null
}>(), {
  activeNodeId: null,
})

const store = useConversationsStore()

const activeFilter = ref<'all' | 'open' | 'closed'>('all')
const showModal = ref(false)

const filters = [
  { label: 'All', value: 'all' as const },
  { label: 'Open', value: 'open' as const },
  { label: 'Closed', value: 'closed' as const },
]

async function setFilter(f: 'all' | 'open' | 'closed') {
  activeFilter.value = f
  await store.refresh(f === 'all' ? undefined : { state: f })
}

function buildRefreshParams(): { state?: string; context_node_id?: string } | undefined {
  const params: { state?: string; context_node_id?: string } = {}
  if (activeFilter.value !== 'all') params.state = activeFilter.value
  if (props.activeNodeId) params.context_node_id = props.activeNodeId
  return Object.keys(params).length > 0 ? params : undefined
}

watch(
  () => props.activeNodeId,
  (nodeId) => {
    if (nodeId) {
      store.refresh({ context_node_id: nodeId })
    } else {
      store.refresh(undefined)
    }
  }
)

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

function onDragStart(conv: ConversationDetail, evt: DragEvent) {
  evt.dataTransfer?.setData('text/plain', JSON.stringify({ conversationId: conv.id }))
}

onMounted(() => {
  store.refresh(buildRefreshParams())
})
</script>

<template>
  <div class="flex flex-col h-full bg-[--bg-1]">
    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-[--border-1] flex-shrink-0">
      <h2 class="font-semibold text-sm text-[--fg-1]">Conversations</h2>
      <button
        type="button"
        class="text-xs px-2 py-1 rounded bg-blue-500 text-white hover:bg-blue-600"
        @click="showModal = true"
      >
        + New
      </button>
    </div>

    <!-- Filter chips -->
    <div class="flex gap-1 px-4 py-2 border-b border-[--border-1] flex-shrink-0">
      <button
        v-for="f in filters"
        :key="f.value"
        type="button"
        class="text-xs px-2 py-1 rounded-full transition-colors"
        :class="activeFilter === f.value
          ? 'bg-blue-500 text-white'
          : 'bg-[--bg-2] text-[--fg-3] hover:bg-[--bg-3]'"
        @click="setFilter(f.value)"
      >
        {{ f.label }}
      </button>
    </div>

    <!-- List -->
    <div class="flex-1 overflow-y-auto">
      <p v-if="store.list.length === 0" class="text-xs text-[--fg-5] text-center py-8">
        No conversations yet.
      </p>
      <ul v-else>
        <li
          v-for="conv in store.list"
          :key="conv.id"
          data-testid="conversation-row"
          draggable="true"
          class="flex flex-col px-4 py-3 border-b border-[--border-1] cursor-pointer hover:bg-[--bg-2] transition-colors"
          :class="store.selectedId === conv.id ? 'bg-[--bg-2]' : ''"
          @click="store.select(conv.id)"
          @dragstart="onDragStart(conv, $event)"
        >
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-medium text-sm text-[--fg-1] truncate flex-1">{{ conv.name }}</span>
            <PriorityPill :priority="conv.priority" />
          </div>
          <div class="flex items-center gap-2 mt-0.5">
            <span v-if="conv.folder_name" class="text-xs text-[--fg-4] truncate">
              {{ conv.folder_name }}
            </span>
            <span class="text-xs text-[--fg-5] ml-auto flex-shrink-0">
              {{ formatRelativeTime(conv.last_message_at) }}
            </span>
          </div>
        </li>
      </ul>
    </div>

    <NewConversationModal
      :open="showModal"
      :context-nodes="[]"
      :default-node-id="activeNodeId"
      @close="showModal = false"
      @created="showModal = false"
    />
  </div>
</template>
