<script setup lang="ts">
import { ref, computed } from 'vue'
import { useContextStore } from '../stores/context'
import type { ContextNode } from '../stores/context'
import { useMilestoneStore } from '../stores/milestones'
import MilestoneDetail from './MilestoneDetail.vue'

const props = withDefaults(defineProps<{
  node: ContextNode
  depth?: number
}>(), {
  depth: 0,
})

const contextStore = useContextStore()
const milestoneStore = useMilestoneStore()

// --- Local state (per-instance) ---
const expanded = ref(false)
const editing = ref(false)
const editBody = ref('')
const renaming = ref(false)
const renameValue = ref('')
const error = ref<string | null>(null)
const addingChild = ref(false)
const newChildName = ref('')
const expandedMilestones = ref<Set<string>>(new Set())
const addingMilestone = ref(false)
const newMilestoneName = ref('')

// --- Computed ---
const children = computed(() => contextStore.childrenOf(props.node.id))
const hasChildren = computed(() => children.value.length > 0 || (props.node.children_count ?? 0) > 0)
const nodeBody = computed(() => contextStore.sectionCache[`${props.node.id}::details`]?.body ?? '')
const milestones = computed(() => milestoneStore.bySubject[props.node.name] ?? [])

const depthStyle = computed(() => ({
  paddingLeft: props.depth * 16 + 'px',
}))

const cardStyle = computed(() => ({
  backgroundColor: 'rgba(255,255,255,' + (0.03 + props.depth * 0.01) + ')',
}))

// --- Actions ---

async function toggleExpand() {
  if (expanded.value) {
    expanded.value = false
    return
  }
  expanded.value = true
  try {
    error.value = null
    const fetched = await contextStore.fetchChildren(props.node.id)
    await Promise.allSettled(fetched.map(c => contextStore.fetchSection(c.id, 'details')))
  } catch (e) {
    expanded.value = false
    console.error('toggleExpand error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to expand node'
  }
}

async function startEdit() {
  editing.value = true
  try {
    const section = await contextStore.fetchSection(props.node.id, 'details')
    editBody.value = section?.body ?? ''
  } catch (e) {
    console.error('startEdit error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to load section'
  }
}

async function saveEdit() {
  try {
    error.value = null
    await contextStore.saveSection(props.node.id, 'details', editBody.value)
    editing.value = false
  } catch (e) {
    console.error('saveEdit error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to save'
  }
}

function startRename() {
  renaming.value = true
  renameValue.value = props.node.name
}

async function saveRename() {
  if (!renameValue.value.trim() || renameValue.value.trim() === props.node.name) {
    renaming.value = false
    return
  }
  try {
    error.value = null
    await contextStore.patchNode(props.node.id, { name: renameValue.value.trim() })
    renaming.value = false
  } catch (e) {
    console.error('saveRename error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to rename'
  }
}

async function deleteWithConfirm() {
  const childCount = children.value.length
  const msg = childCount > 0
    ? `Delete "${props.node.name}" and ${childCount} sub-entr${childCount === 1 ? 'y' : 'ies'}?`
    : `Delete "${props.node.name}"?`
  if (!confirm(msg)) return
  try {
    error.value = null
    await contextStore.deleteNode(props.node.id)
  } catch (e) {
    console.error('deleteWithConfirm error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to delete'
  }
}

async function addChild() {
  if (!newChildName.value.trim()) return
  try {
    error.value = null
    await contextStore.createNode(props.node.id, newChildName.value.trim())
    await contextStore.fetchChildren(props.node.id)
    newChildName.value = ''
    addingChild.value = false
    if (!expanded.value) expanded.value = true
  } catch (e) {
    console.error('addChild error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add child'
  }
}

function toggleMilestone(id: string) {
  const next = new Set(expandedMilestones.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  expandedMilestones.value = next
}

async function addMilestone() {
  if (!newMilestoneName.value.trim()) return
  try {
    error.value = null
    await milestoneStore.createMilestone(props.node.name, newMilestoneName.value.trim())
    newMilestoneName.value = ''
    addingMilestone.value = false
  } catch (e) {
    console.error('addMilestone error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add milestone'
  }
}
</script>

<template>
  <div :style="depthStyle">
    <div class="border border-white/10 rounded-xl p-4" :style="cardStyle">
      <!-- Error -->
      <p v-if="error" class="text-red-400 text-sm mb-2">{{ error }}</p>

      <!-- Header row -->
      <div class="flex justify-between items-center mb-2">
        <div class="flex items-center gap-2 flex-1 min-w-0">
          <button v-if="hasChildren"
                  @click="toggleExpand"
                  class="text-white/40 hover:text-white/80 text-xs w-4 shrink-0">
            {{ expanded ? '\u25BC' : '\u25B6' }}
          </button>
          <span v-else class="w-4 shrink-0" />

          <template v-if="renaming">
            <input v-model="renameValue"
                   @keyup.enter="saveRename"
                   @keyup.escape="renaming = false"
                   class="flex-1 bg-transparent border-b border-white/40 text-sm outline-none" />
            <span v-if="children.length > 0"
                  class="text-xs text-yellow-400/70 ml-1">
              (renames node, {{ children.length }} children unaffected)
            </span>
          </template>
          <h3 v-else class="font-semibold text-sm truncate">{{ node.name }}</h3>
        </div>

        <div class="flex gap-2 shrink-0">
          <button @click="startEdit"
                  class="text-xs text-white/50 hover:text-white">Edit</button>
          <template v-if="renaming">
            <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
            <button @click="renaming = false" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
          </template>
          <button v-else @click="startRename"
                  class="text-xs text-white/50 hover:text-white">Rename</button>
          <button @click="deleteWithConfirm"
                  class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
        </div>
      </div>

      <!-- Edit mode -->
      <div v-if="editing">
        <textarea v-model="editBody" rows="4"
                  class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
        <div class="flex gap-2 mt-2">
          <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
          <button @click="editing = false" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
        </div>
      </div>
      <!-- Body display -->
      <p v-else class="text-xs text-white/50 line-clamp-2">{{ nodeBody || '(empty)' }}</p>

      <!-- Milestone chips -->
      <div v-if="milestones.length" class="mt-2 flex flex-wrap gap-1">
        <button
          v-for="m in milestones" :key="m.id"
          @click="toggleMilestone(m.id)"
          :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
          class="text-xs px-1.5 py-0.5 rounded border flex items-center gap-1"
          :class="m.color ? 'hover:opacity-80' : 'bg-white/10 hover:bg-white/20 border-transparent'">
          <span :class="m.status === 'done' ? 'bg-green-400'
                      : m.status === 'in_progress' ? 'bg-blue-400'
                      : m.status === 'blocked' ? 'bg-red-400' : 'bg-white/20'"
                class="w-1.5 h-1.5 rounded-full" />
          {{ m.name }} {{ m.done_count }}/{{ m.task_count }}
        </button>
      </div>
      <template v-for="m in milestones" :key="'detail-' + m.id">
        <MilestoneDetail
          v-if="expandedMilestones.has(m.id)"
          :milestone="m"
          @close="toggleMilestone(m.id)" />
      </template>
      <div v-if="addingMilestone" class="mt-2 flex gap-2">
        <input v-model="newMilestoneName" placeholder="Milestone name..."
               @keydown.enter="addMilestone"
               class="flex-1 bg-transparent border-b border-white/30 outline-none text-xs" />
        <button @click="addMilestone" class="text-xs text-white/60 hover:text-white">Add</button>
        <button @click="addingMilestone = false; newMilestoneName = ''"
                class="text-xs text-white/40">cancel</button>
      </div>
      <button v-else @click="addingMilestone = true"
              class="mt-1 text-xs text-white/30 hover:text-white/60">+ milestone</button>

      <!-- Children (expanded) -->
      <template v-if="expanded">
        <div class="mt-3 flex flex-col gap-3">
          <ContextTreeNode
            v-for="child in children"
            :key="child.id"
            :node="child"
            :depth="depth + 1" />
        </div>

        <!-- Add child button / form -->
        <div v-if="addingChild" class="mt-2 flex gap-2" :style="{ paddingLeft: (depth + 1) * 16 + 'px' }">
          <input v-model="newChildName" placeholder="New child name..."
                 @keyup.enter="addChild"
                 @keyup.escape="addingChild = false"
                 class="flex-1 bg-transparent border-b border-white/30 outline-none text-xs" />
          <button @click="addChild" class="text-xs text-white/60 hover:text-white">Add</button>
          <button @click="addingChild = false; newChildName = ''"
                  class="text-xs text-white/40">cancel</button>
        </div>
        <button v-else @click="addingChild = true"
                class="mt-2 text-xs text-white/40 hover:text-white/70"
                :style="{ paddingLeft: (depth + 1) * 16 + 'px' }">
          + Add child
        </button>
      </template>
    </div>
  </div>
</template>
