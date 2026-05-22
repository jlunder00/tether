<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useContextStore } from '../../stores/context'
import type { ContextNode } from '../../stores/context'
import { useConversationsStore } from '../../stores/conversations'

defineProps<{ activeNodeId: string | null }>()
const emit = defineEmits<{ 'update:activeNodeId': [id: string | null] }>()

const contextStore = useContextStore()
const conversationsStore = useConversationsStore()

// Track expanded nodes
const expandedNodes = ref<Set<string>>(new Set())
// Track which node is being dragged over
const dragOverNodeId = ref<string | null>(null)

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
  }
}

function hasChildren(node: ContextNode): boolean {
  // Show chevron if children_count is set and > 0, OR if undefined (unknown, optimistically show)
  if (node.children_count === undefined) return false
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
</script>

<template>
  <div class="flex flex-col h-full bg-[--bg-1] text-sm">
    <!-- Header -->
    <div class="px-3 py-3 border-b border-[--border-1] flex-shrink-0">
      <span class="font-semibold text-xs text-[--fg-3] uppercase tracking-wide">Context</span>
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

        <!-- Children (indented) -->
        <template v-if="expandedNodes.has(node.id)">
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
        </template>
      </template>
    </div>
  </div>
</template>
