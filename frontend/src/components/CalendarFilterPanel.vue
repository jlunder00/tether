<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ContextNode } from '../stores/context'
import type { Anchor } from '../stores/anchors'
import type { KanbanColumn } from '../stores/kanban'
import ContextTreeFilterNode from './ContextTreeFilterNode.vue'

export interface CalendarFilter {
  contextNodeIds: Set<string>
  anchorIds: Set<string>
  kanbanColumnIds: Set<string>
}

const props = defineProps<{
  modelValue: CalendarFilter
  rootNodes: ContextNode[]
  childrenOf: (parentId: string) => ContextNode[]
  fetchChildren?: (parentId: string) => Promise<unknown>
  anchors: Anchor[]
  kanbanColumns: KanbanColumn[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: CalendarFilter): void
  (e: 'close'): void
}>()

const search = ref('')
const collapsed = ref<Record<string, boolean>>({ categories: false, anchors: false, kanban: false })
const searchLower = computed(() => search.value.toLowerCase())

function clone(): CalendarFilter {
  return {
    contextNodeIds: new Set(props.modelValue.contextNodeIds),
    anchorIds: new Set(props.modelValue.anchorIds),
    kanbanColumnIds: new Set(props.modelValue.kanbanColumnIds),
  }
}

function toggleContextNode(id: string) {
  const f = clone()
  if (f.contextNodeIds.has(id)) f.contextNodeIds.delete(id)
  else f.contextNodeIds.add(id)
  emit('update:modelValue', f)
}

function toggleAnchor(id: string) {
  const f = clone()
  if (f.anchorIds.has(id)) f.anchorIds.delete(id)
  else f.anchorIds.add(id)
  emit('update:modelValue', f)
}

function toggleKanban(id: string) {
  const f = clone()
  if (f.kanbanColumnIds.has(id)) f.kanbanColumnIds.delete(id)
  else f.kanbanColumnIds.add(id)
  emit('update:modelValue', f)
}

function toggleGroup(key: string) { collapsed.value[key] = !collapsed.value[key] }

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

const totalActive = computed(() =>
  props.modelValue.contextNodeIds.size +
  props.modelValue.anchorIds.size +
  props.modelValue.kanbanColumnIds.size
)

const filteredAnchors = computed(() =>
  props.anchors.filter(a => a.name.toLowerCase().includes(searchLower.value))
)
const filteredKanban = computed(() =>
  props.kanbanColumns.filter(c => c.name.toLowerCase().includes(searchLower.value))
)
</script>

<template>
  <div
    class="w-72 max-h-[70vh] overflow-y-auto bg-gray-800 border border-white/20 rounded-xl shadow-xl p-3 space-y-1"
    tabindex="0"
    @keydown="onKeydown"
  >
    <input
      v-model="search"
      data-testid="filter-search"
      placeholder="Search filters…"
      class="w-full text-xs bg-white/5 border border-white/10 rounded px-2 py-1.5 text-white placeholder-white/30 outline-none focus:border-indigo-500 mb-2"
    />

    <div class="flex items-center justify-between mb-1">
      <span class="text-[10px] text-white/30 uppercase tracking-wide">Filters</span>
      <button
        v-if="totalActive > 0"
        class="text-[10px] text-indigo-400 hover:text-indigo-300"
        @click="emit('update:modelValue', { contextNodeIds: new Set(), anchorIds: new Set(), kanbanColumnIds: new Set() })"
      >Clear all ({{ totalActive }})</button>
    </div>

    <!-- Categories (context tree, milestones included) -->
    <div>
      <button
        data-testid="filter-group-categories"
        class="flex items-center gap-1 w-full text-left text-[10px] text-white/40 uppercase tracking-wide py-1 hover:text-white/60"
        @click="toggleGroup('categories')"
      >
        <span class="transition-transform" :class="collapsed.categories ? '-rotate-90' : ''">▾</span>
        Categories
        <span v-if="modelValue.contextNodeIds.size > 0" class="ml-auto text-indigo-400">{{ modelValue.contextNodeIds.size }}</span>
      </button>
      <div v-if="!collapsed.categories" class="pl-1">
        <div v-if="!rootNodes.length" class="text-[11px] text-white/20 py-0.5">No categories</div>
        <ContextTreeFilterNode
          v-for="n in rootNodes"
          :key="n.id"
          :node="n"
          :selected="modelValue.contextNodeIds"
          :children-of="childrenOf"
          :fetch-children="fetchChildren"
          :search="searchLower"
          @toggle="toggleContextNode"
        />
      </div>
    </div>

    <!-- Anchors -->
    <div>
      <button
        data-testid="filter-group-anchors"
        class="flex items-center gap-1 w-full text-left text-[10px] text-white/40 uppercase tracking-wide py-1 hover:text-white/60"
        @click="toggleGroup('anchors')"
      >
        <span class="transition-transform" :class="collapsed.anchors ? '-rotate-90' : ''">▾</span>
        Anchors
        <span v-if="modelValue.anchorIds.size > 0" class="ml-auto text-indigo-400">{{ modelValue.anchorIds.size }}</span>
      </button>
      <div v-if="!collapsed.anchors" class="space-y-0.5 pl-2">
        <div v-if="!filteredAnchors.length" class="text-[11px] text-white/20 py-0.5">No matches</div>
        <button
          v-for="a in filteredAnchors"
          :key="a.id"
          :data-testid="`filter-item-anchor-${a.id}`"
          class="flex items-center gap-2 w-full text-left px-2 py-1 rounded text-xs transition-colors"
          :class="modelValue.anchorIds.has(a.id) ? 'bg-indigo-500/20 text-indigo-200' : 'text-white/60 hover:bg-white/5'"
          @click="toggleAnchor(a.id)"
        >
          <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ backgroundColor: a.color || '#6366f1' }" />
          <span class="flex-1 truncate">{{ a.name }}</span>
          <span class="text-[10px] text-white/30">{{ a.time }}</span>
        </button>
      </div>
    </div>

    <!-- Kanban Columns -->
    <div>
      <button
        data-testid="filter-group-kanban"
        class="flex items-center gap-1 w-full text-left text-[10px] text-white/40 uppercase tracking-wide py-1 hover:text-white/60"
        @click="toggleGroup('kanban')"
      >
        <span class="transition-transform" :class="collapsed.kanban ? '-rotate-90' : ''">▾</span>
        Kanban Columns
        <span v-if="modelValue.kanbanColumnIds.size > 0" class="ml-auto text-indigo-400">{{ modelValue.kanbanColumnIds.size }}</span>
      </button>
      <div v-if="!collapsed.kanban" class="space-y-0.5 pl-2">
        <div v-if="!filteredKanban.length" class="text-[11px] text-white/20 py-0.5">No matches</div>
        <button
          v-for="c in filteredKanban"
          :key="c.id"
          :data-testid="`filter-item-kanban-${c.id}`"
          class="flex items-center gap-2 w-full text-left px-2 py-1 rounded text-xs transition-colors"
          :class="modelValue.kanbanColumnIds.has(c.id) ? 'bg-indigo-500/20 text-indigo-200' : 'text-white/60 hover:bg-white/5'"
          @click="toggleKanban(c.id)"
        >
          <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ backgroundColor: c.color ?? '#6366f1' }" />
          {{ c.name }}
        </button>
      </div>
    </div>

    <div class="flex justify-end mt-2">
      <button class="text-[10px] text-white/30 hover:text-white/60" @click="emit('close')">Done</button>
    </div>
  </div>
</template>
