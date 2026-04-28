<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ContextNode } from '../stores/context'

const props = defineProps<{
  node: ContextNode
  selected: Set<string>
  childrenOf: (parentId: string) => ContextNode[]
  fetchChildren?: (parentId: string) => Promise<unknown>
  search: string
  depth?: number
}>()

const emit = defineEmits<{
  (e: 'toggle', id: string): void
}>()

const expanded = ref(false)
const fetched = ref(false)

const children = computed(() => props.childrenOf(props.node.id))
// Heuristic: a node may have children even if none are loaded yet.
// children_count is populated when fetched via single-node GET; default to assuming
// expandable so the user can try.
const mayHaveChildren = computed(() => {
  if (children.value.length > 0) return true
  if (props.node.children_count !== undefined) return props.node.children_count > 0
  return !fetched.value
})

const matchesSearch = computed(() => {
  if (!props.search) return true
  return props.node.name.toLowerCase().includes(props.search)
})

async function onToggleExpand() {
  expanded.value = !expanded.value
  if (expanded.value && !fetched.value && children.value.length === 0 && props.fetchChildren) {
    try { await props.fetchChildren(props.node.id) } catch { /* ignore */ }
    fetched.value = true
  }
}

const isSelected = computed(() => props.selected.has(props.node.id))
const isMilestone = computed(() => props.node.node_type === 'milestone')
</script>

<template>
  <div v-show="matchesSearch || expanded" class="context-tree-node">
    <div class="flex items-center gap-1 group">
      <button
        v-if="mayHaveChildren"
        class="w-4 h-4 flex-shrink-0 text-white/40 hover:text-white text-[10px]"
        :data-testid="`tree-expand-${node.id}`"
        @click="onToggleExpand"
      >{{ expanded ? '▾' : '▸' }}</button>
      <span v-else class="w-4 flex-shrink-0" />

      <button
        :data-testid="`filter-item-context-${node.id}`"
        class="flex items-center gap-2 flex-1 text-left px-2 py-1 rounded text-xs transition-colors min-w-0"
        :class="isSelected ? 'bg-indigo-500/20 text-indigo-200' : 'text-white/60 hover:bg-white/5'"
        @click="emit('toggle', node.id)"
      >
        <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ backgroundColor: node.color ?? '#6366f1' }" />
        <span class="truncate">{{ node.name }}</span>
        <span v-if="isMilestone" class="text-[9px] text-white/30 uppercase tracking-wide ml-auto flex-shrink-0">M</span>
      </button>
    </div>

    <div v-if="expanded && children.length" class="pl-3">
      <ContextTreeFilterNode
        v-for="child in children"
        :key="child.id"
        :node="child"
        :selected="selected"
        :children-of="childrenOf"
        :fetch-children="fetchChildren"
        :search="search"
        :depth="(depth ?? 0) + 1"
        @toggle="(id: string) => emit('toggle', id)"
      />
    </div>
  </div>
</template>
