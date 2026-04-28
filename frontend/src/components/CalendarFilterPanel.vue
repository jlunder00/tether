<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Milestone } from '../stores/milestones'
import type { ContextNode } from '../stores/context'
import type { KanbanColumn } from '../stores/kanban'

export interface CalendarFilter {
  milestoneIds: Set<string>
  contextNodeIds: Set<string>
  kanbanColumnIds: Set<string>
}

const props = defineProps<{
  modelValue: CalendarFilter
  milestones: Milestone[]
  contextNodes: ContextNode[]
  kanbanColumns: KanbanColumn[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: CalendarFilter): void
  (e: 'close'): void
}>()

const search = ref('')
const collapsed = ref<Record<string, boolean>>({ milestones: false, context: false, kanban: false })

const searchLower = computed(() => search.value.toLowerCase())

const filteredMilestones = computed(() =>
  props.milestones.filter(m => m.name.toLowerCase().includes(searchLower.value))
)
const filteredContextNodes = computed(() =>
  props.contextNodes.filter(n => n.name.toLowerCase().includes(searchLower.value))
)
const filteredKanbanColumns = computed(() =>
  props.kanbanColumns.filter(c => c.name.toLowerCase().includes(searchLower.value))
)

function toggleGroup(key: string) {
  collapsed.value[key] = !collapsed.value[key]
}

function clone(): CalendarFilter {
  return {
    milestoneIds: new Set(props.modelValue.milestoneIds),
    contextNodeIds: new Set(props.modelValue.contextNodeIds),
    kanbanColumnIds: new Set(props.modelValue.kanbanColumnIds),
  }
}

function toggleMilestone(id: string) {
  const f = clone()
  if (f.milestoneIds.has(id)) f.milestoneIds.delete(id)
  else f.milestoneIds.add(id)
  emit('update:modelValue', f)
}

function toggleContextNode(id: string) {
  const f = clone()
  if (f.contextNodeIds.has(id)) f.contextNodeIds.delete(id)
  else f.contextNodeIds.add(id)
  emit('update:modelValue', f)
}

function toggleKanban(id: string) {
  const f = clone()
  if (f.kanbanColumnIds.has(id)) f.kanbanColumnIds.delete(id)
  else f.kanbanColumnIds.add(id)
  emit('update:modelValue', f)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

const totalActive = computed(() =>
  props.modelValue.milestoneIds.size +
  props.modelValue.contextNodeIds.size +
  props.modelValue.kanbanColumnIds.size
)
</script>

<template>
  <div
    class="w-72 bg-gray-800 border border-white/20 rounded-xl shadow-xl p-3 space-y-1"
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
        @click="emit('update:modelValue', { milestoneIds: new Set(), contextNodeIds: new Set(), kanbanColumnIds: new Set() })"
      >Clear all ({{ totalActive }})</button>
    </div>

    <!-- Milestones group -->
    <div>
      <button
        data-testid="filter-group-milestones"
        class="flex items-center gap-1 w-full text-left text-[10px] text-white/40 uppercase tracking-wide py-1 hover:text-white/60"
        @click="toggleGroup('milestones')"
      >
        <span class="transition-transform" :class="collapsed.milestones ? '-rotate-90' : ''">▾</span>
        Milestones
        <span v-if="modelValue.milestoneIds.size > 0" class="ml-auto text-indigo-400">{{ modelValue.milestoneIds.size }}</span>
      </button>
      <div v-if="!collapsed.milestones" class="space-y-0.5 pl-2">
        <div v-if="!filteredMilestones.length" class="text-[11px] text-white/20 py-0.5">No matches</div>
        <button
          v-for="m in filteredMilestones"
          :key="m.id"
          :data-testid="`filter-item-milestone-${m.id}`"
          class="flex items-center gap-2 w-full text-left px-2 py-1 rounded text-xs transition-colors"
          :class="modelValue.milestoneIds.has(m.id) ? 'bg-indigo-500/20 text-indigo-200' : 'text-white/60 hover:bg-white/5'"
          @click="toggleMilestone(m.id)"
        >
          <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ backgroundColor: m.color ?? '#6366f1' }" />
          {{ m.name }}
        </button>
      </div>
    </div>

    <!-- Context Nodes group -->
    <div>
      <button
        data-testid="filter-group-context"
        class="flex items-center gap-1 w-full text-left text-[10px] text-white/40 uppercase tracking-wide py-1 hover:text-white/60"
        @click="toggleGroup('context')"
      >
        <span class="transition-transform" :class="collapsed.context ? '-rotate-90' : ''">▾</span>
        Context Nodes
        <span v-if="modelValue.contextNodeIds.size > 0" class="ml-auto text-indigo-400">{{ modelValue.contextNodeIds.size }}</span>
      </button>
      <div v-if="!collapsed.context" class="space-y-0.5 pl-2">
        <div v-if="!filteredContextNodes.length" class="text-[11px] text-white/20 py-0.5">No matches</div>
        <button
          v-for="n in filteredContextNodes"
          :key="n.id"
          :data-testid="`filter-item-context-${n.id}`"
          class="flex items-center gap-2 w-full text-left px-2 py-1 rounded text-xs transition-colors"
          :class="modelValue.contextNodeIds.has(n.id) ? 'bg-indigo-500/20 text-indigo-200' : 'text-white/60 hover:bg-white/5'"
          @click="toggleContextNode(n.id)"
        >
          <span class="w-2 h-2 rounded-full flex-shrink-0" :style="{ backgroundColor: n.color ?? '#6366f1' }" />
          {{ n.name }}
        </button>
      </div>
    </div>

    <!-- Kanban Columns group -->
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
        <div v-if="!filteredKanbanColumns.length" class="text-[11px] text-white/20 py-0.5">No matches</div>
        <button
          v-for="c in filteredKanbanColumns"
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
