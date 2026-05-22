<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useContextStore } from '../../stores/context'
import type { ContextNode } from '../../stores/context'
import { useConversationsStore } from '../../stores/conversations'
import type { ConversationDetail } from '../../types/conversations'

defineProps<{ activeNodeId: string | null }>()
const emit = defineEmits<{
  'update:activeNodeId': [id: string | null]
  'collapse': []
}>()

const contextStore = useContextStore()
const conversationsStore = useConversationsStore()

// Track expanded nodes
const expandedNodes = ref<Set<string>>(new Set())
// Track which node is being dragged over
const dragOverNodeId = ref<string | null>(null)
// Map of nodeId → conversations fetched for that node
const convsByNode = ref<Map<string, ConversationDetail[]>>(new Map())

onMounted(() => {
  contextStore.fetchRootNodes()
})

function selectAll() {
  emit('update:activeNodeId', null)
}

function selectNode(nodeId: string) {
  emit('update:activeNodeId', nodeId)
}

async function toggleExpand(node: ContextNode, evt: Event) {
  evt.stopPropagation()
  const id = node.id
  if (expandedNodes.value.has(id)) {
    expandedNodes.value = new Set([...expandedNodes.value].filter(x => x !== id))
  } else {
    expandedNodes.value = new Set([...expandedNodes.value, id])
    await contextStore.fetchChildren(id)
    // Fetch conversations scoped to this node
    await conversationsStore.refresh({ context_node_id: id })
    convsByNode.value = new Map(convsByNode.value).set(
      id,
      conversationsStore.list.filter(c => c.context_node_id === id)
    )
  }
}

function hasChildren(node: ContextNode): boolean {
  if (node.children_count === undefined) return true
  return node.children_count > 0
}

function onDragOver(nodeId: string, evt: DragEvent) {
  evt.preventDefault()
  dragOverNodeId.value = nodeId
}

function onDragLeave(nodeId: string) {
  if (dragOverNodeId.value === nodeId) {
    dragOverNodeId.value = null
  }
}

async function onDrop(nodeId: string, evt: DragEvent) {
  evt.preventDefault()
  dragOverNodeId.value = null
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const { conversationId } = JSON.parse(raw)
    if (conversationId) {
      await conversationsStore.assignNode(conversationId, nodeId)
    }
  } catch {
    // ignore malformed data
  }
}

function onConvLeafDragStart(conv: ConversationDetail, evt: DragEvent) {
  evt.dataTransfer?.setData('text/plain', JSON.stringify({ conversationId: conv.id }))
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

// + New chat: emit update:activeNodeId with the folder's id — switches
// FolderCenterPanel to that folder's composer with that folder as default scope.
function startNewChat(nodeId: string) {
  emit('update:activeNodeId', nodeId)
}
</script>

<template>
  <div class="flex flex-col h-full bg-[--bg-1] text-sm" style="width:240px;flex-shrink:0;border-right:1px solid var(--border-1);">
    <!-- Header -->
    <div class="px-3 py-2.5 border-b border-[--border-1] flex-shrink-0 flex items-center justify-between">
      <span class="font-semibold text-[10px] text-[--fg-5] uppercase tracking-widest font-mono">Chat</span>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="sidebar-icon-btn"
          title="New chat"
          @click="emit('update:activeNodeId', null)"
        >
          +
        </button>
        <button
          data-testid="sidebar-collapse-btn"
          type="button"
          class="sidebar-icon-btn"
          title="Collapse"
          @click="emit('collapse')"
        >
          ‹
        </button>
      </div>
    </div>

    <!-- All item -->
    <div
      data-testid="all-item"
      class="flex items-center px-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors"
      :class="activeNodeId === null ? 'bg-[--bg-elev-3] font-medium' : ''"
      @click="selectAll"
    >
      <span class="text-[--fg-2] text-xs">All conversations</span>
    </div>

    <!-- Root nodes -->
    <div class="flex-1 overflow-y-auto">
      <template v-for="node in contextStore.rootNodes" :key="node.id">
        <!-- Node row (also drop zone) -->
        <div
          :data-testid="`drop-zone-${node.id}`"
          class="flex items-center gap-1 px-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors"
          :class="[
            activeNodeId === node.id ? 'bg-[--bg-elev-3] font-medium' : '',
            dragOverNodeId === node.id ? 'ring-2 ring-blue-400/50' : '',
          ]"
          @dragover="onDragOver(node.id, $event)"
          @dragleave="onDragLeave(node.id)"
          @drop="onDrop(node.id, $event)"
        >
          <!-- Expand chevron -->
          <button
            v-if="hasChildren(node)"
            :data-testid="`expand-chevron-${node.id}`"
            type="button"
            class="w-4 h-4 flex items-center justify-center text-[--fg-4] hover:text-[--fg-1] flex-shrink-0"
            @click.stop="toggleExpand(node, $event)"
          >
            <svg
              class="w-3 h-3 transition-transform"
              :class="expandedNodes.has(node.id) ? 'rotate-90' : ''"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <span v-else class="w-4 flex-shrink-0" />

          <!-- Node name -->
          <span
            :data-testid="`node-row-${node.id}`"
            class="text-[--fg-2] text-xs truncate flex-1"
            @click="selectNode(node.id)"
          >
            {{ node.name }}
          </span>
        </div>

        <!-- Children + conversation leaves (when expanded) -->
        <template v-if="expandedNodes.has(node.id)">
          <!-- Child folder nodes (indented) -->
          <div
            v-for="child in contextStore.childrenOf(node.id)"
            :key="child.id"
            :data-testid="`drop-zone-${child.id}`"
            class="flex items-center gap-1 pl-8 pr-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors"
            :class="[
              activeNodeId === child.id ? 'bg-[--bg-elev-3] font-medium' : '',
              dragOverNodeId === child.id ? 'ring-2 ring-blue-400/50' : '',
            ]"
            @dragover="onDragOver(child.id, $event)"
            @dragleave="onDragLeave(child.id)"
            @drop="onDrop(child.id, $event)"
          >
            <span
              :data-testid="`node-row-${child.id}`"
              class="text-[--fg-2] text-xs truncate flex-1"
              @click="selectNode(child.id)"
            >
              {{ child.name }}
            </span>
          </div>

          <!-- Conversation leaf items -->
          <div
            v-for="conv in convsByNode.get(node.id) ?? []"
            :key="conv.id"
            :data-testid="`conv-leaf-${conv.id}`"
            class="tree-conv-item"
            :class="conversationsStore.selectedId === conv.id ? 'tree-conv-item--active' : ''"
            draggable="true"
            @click="emit('update:activeNodeId', null); conversationsStore.select(conv.id)"
            @dragstart="onConvLeafDragStart(conv, $event)"
          >
            <span class="tree-conv-dot" />
            <span class="flex-1 truncate text-xs">{{ conv.name }}</span>
            <span class="tree-conv-ts">{{ relativeTime(conv.last_message_at) }}</span>
          </div>

          <!-- + New chat affordance -->
          <div class="tree-new-chat" @click="startNewChat(node.id)">
            + New chat
          </div>
        </template>
      </template>
    </div>
  </div>
</template>

<style scoped>
.tree-conv-item {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 10px 5px 48px;
  font-size: 12px; color: var(--fg-3);
  cursor: pointer; min-height: 26px;
  transition: background 150ms;
}
.tree-conv-item:hover         { background: var(--bg-elev-2); }
.tree-conv-item--active       { background: var(--bg-elev-3); color: var(--fg-1); }

.tree-conv-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0;
  visibility: hidden;
}

.tree-conv-ts {
  font-family: var(--font-mono); font-size: 9.5px;
  color: var(--fg-5); flex-shrink: 0; padding-right: 4px;
}

.tree-new-chat {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 10px 6px 48px;
  font-family: var(--font-mono); font-size: 11px;
  color: var(--accent); cursor: pointer; opacity: 0.7;
  transition: opacity 150ms;
}
.tree-new-chat:hover           { opacity: 1; }

.sidebar-icon-btn {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent; cursor: pointer;
  border-radius: var(--radius-sharp); color: var(--fg-4);
  transition: background 150ms, color 150ms;
}
.sidebar-icon-btn:hover { background: var(--bg-elev-3); color: var(--fg-2); }
</style>
