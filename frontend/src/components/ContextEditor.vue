<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useContextStore } from '../stores/context'
import type { ContextNode } from '../stores/context'
import MilestoneDetail from './MilestoneDetail.vue'
import { useMilestoneStore } from '../stores/milestones'

const store = useContextStore()
const editing = ref<string | null>(null) // node id being edited
const editBody = ref('')
const renaming = ref<string | null>(null) // node id being renamed
const renameValue = ref('')
const newSubject = ref('')
const expandedGroups = ref<Set<string>>(new Set()) // node ids
const error = ref<string | null>(null)

const milestoneStore = useMilestoneStore()
const expandedMilestones = ref<Set<string>>(new Set())
const addingMilestoneFor = ref<string | null>(null) // node id
const newMilestoneName = ref('')

function toggleMilestone(id: string) {
  const next = new Set(expandedMilestones.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  expandedMilestones.value = next
}

async function addMilestone(nodeName: string) {
  if (!newMilestoneName.value.trim()) return
  try {
    error.value = null
    await milestoneStore.createMilestone(nodeName, newMilestoneName.value.trim())
    newMilestoneName.value = ''
    addingMilestoneFor.value = null
  } catch (e) {
    console.error('addMilestone error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add milestone'
  }
}

async function toggleExpand(node: ContextNode) {
  if (expandedGroups.value.has(node.id)) {
    expandedGroups.value.delete(node.id)
  } else {
    // Optimistic: add to expanded set before fetch
    expandedGroups.value.add(node.id)
    try {
      const children = await store.fetchChildren(node.id)
      await Promise.allSettled(children.map(c => store.fetchSection(c.id, 'details')))
    } catch (e) {
      // Rollback on error
      expandedGroups.value.delete(node.id)
      console.error('toggleExpand error:', e)
      error.value = e instanceof Error ? e.message : 'Failed to expand node'
    }
  }
}

async function startEdit(nodeId: string) {
  editing.value = nodeId
  // Fetch the 'details' section for this node
  const section = await store.fetchSection(nodeId, 'details')
  editBody.value = section?.body ?? ''
}

async function saveEdit() {
  if (!editing.value) return
  try {
    error.value = null
    await store.saveSection(editing.value, 'details', editBody.value)
    editing.value = null
  } catch (e) {
    console.error('saveEdit error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to save'
  }
}

function startRename(nodeId: string, currentName: string) {
  renaming.value = nodeId
  renameValue.value = currentName
}

async function saveRename() {
  if (!renaming.value || !renameValue.value.trim()) {
    renaming.value = null
    return
  }
  const node = store.nodes[renaming.value]
  if (!node || renameValue.value.trim() === node.name) {
    renaming.value = null
    return
  }
  try {
    error.value = null
    await store.patchNode(renaming.value, { name: renameValue.value.trim() })
    renaming.value = null
  } catch (e) {
    console.error('saveRename error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to rename'
  }
}

async function addEntry() {
  if (!newSubject.value.trim()) return
  try {
    error.value = null
    const parts = newSubject.value.trim().split('/')
    if (parts.length === 1) {
      // Root node
      await store.createNode(null, parts[0])
    } else {
      // Nested: find or create parent, then create child
      const parentName = parts[0]
      let parent = store.nodeByName(parentName, null)
      if (!parent) {
        parent = await store.createNode(null, parentName)
      }
      const childName = parts.slice(1).join('/')
      await store.createNode(parent.id, childName)
    }
    await store.fetchRootNodes()
    newSubject.value = ''
  } catch (e) {
    console.error('addEntry error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add entry'
  }
}

function prefillSubEntry(parentName: string) {
  newSubject.value = parentName + '/'
}

async function deleteWithConfirm(node: ContextNode) {
  const children = store.childrenOf(node.id)
  const childCount = children.length
  const msg = childCount > 0
    ? `Delete "${node.name}" and ${childCount} sub-entr${childCount === 1 ? 'y' : 'ies'}?`
    : `Delete "${node.name}"?`
  if (!confirm(msg)) return
  try {
    error.value = null
    await store.deleteNode(node.id)
  } catch (e) {
    console.error('deleteWithConfirm error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to delete'
  }
}

/** Get the cached details body for display (without fetching) */
function nodeBody(nodeId: string): string {
  return store.sectionCache[`${nodeId}::details`]?.body ?? ''
}

/** Load sections for all root context nodes (for display bodies) */
async function loadRootSections() {
  const nodes = store.rootContextNodes
  await Promise.allSettled(nodes.map(n => store.fetchSection(n.id, 'details')))
}

onMounted(async () => {
  try {
    await store.fetchRootNodes()
    await loadRootSections()
    await milestoneStore.fetchAll()
  } catch (e) {
    console.error('ContextEditor mount error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to load context data'
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
  <p v-if="error" class="text-red-400 text-sm">{{ error }}</p>
  <div class="space-y-3">
    <template v-for="node in store.rootContextNodes" :key="node.id">
      <!-- Top-level entry -->
      <div class="bg-white/5 border border-white/10 rounded-xl p-4">
        <div class="flex justify-between items-center mb-2">
          <div class="flex items-center gap-2 flex-1 min-w-0">
            <button v-if="store.childrenOf(node.id).length > 0 || (node.children_count ?? 0) > 0"
                    @click="toggleExpand(node)"
                    class="text-white/40 hover:text-white/80 text-xs w-4 shrink-0">
              {{ expandedGroups.has(node.id) ? '\u25BC' : '\u25B6' }}
            </button>
            <span v-else class="w-4 shrink-0" />

            <template v-if="renaming === node.id">
              <input v-model="renameValue" @keyup.enter="saveRename" @keyup.escape="renaming = null"
                     class="flex-1 bg-transparent border-b border-white/40 text-sm outline-none" />
              <span v-if="store.childrenOf(node.id).length > 0"
                    class="text-xs text-yellow-400/70 ml-1">
                (renames node, {{ store.childrenOf(node.id).length }} children unaffected)
              </span>
            </template>
            <h3 v-else class="font-semibold text-sm truncate">{{ node.name }}</h3>
          </div>

          <div class="flex gap-2 shrink-0">
            <button @click="startEdit(node.id)"
                    class="text-xs text-white/50 hover:text-white">Edit</button>
            <template v-if="renaming === node.id">
              <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
              <button @click="renaming = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
            </template>
            <button v-else @click="startRename(node.id, node.name)"
                    class="text-xs text-white/50 hover:text-white">Rename</button>
            <button @click="deleteWithConfirm(node)"
                    class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
          </div>
        </div>

        <div v-if="editing === node.id">
          <textarea v-model="editBody" rows="4"
                    class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
          <div class="flex gap-2 mt-2">
            <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
            <button @click="editing = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
          </div>
        </div>
        <p v-else class="text-xs text-white/50 line-clamp-2">{{ nodeBody(node.id) || '(empty)' }}</p>

        <!-- Milestone chips -->
        <div v-if="milestoneStore.bySubject[node.name]?.length" class="mt-2 flex flex-wrap gap-1">
          <button
            v-for="m in milestoneStore.bySubject[node.name]" :key="m.id"
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
        <template v-for="m in milestoneStore.bySubject[node.name]" :key="'detail-' + m.id">
          <MilestoneDetail
            v-if="expandedMilestones.has(m.id)"
            :milestone="m"
            @close="toggleMilestone(m.id)" />
        </template>
        <div v-if="addingMilestoneFor === node.id" class="mt-2 flex gap-2">
          <input v-model="newMilestoneName" placeholder="Milestone name..."
                 @keydown.enter="addMilestone(node.name)"
                 class="flex-1 bg-transparent border-b border-white/30 outline-none text-xs" />
          <button @click="addMilestone(node.name)" class="text-xs text-white/60 hover:text-white">Add</button>
          <button @click="addingMilestoneFor = null; newMilestoneName = ''"
                  class="text-xs text-white/40">cancel</button>
        </div>
        <button v-else @click="addingMilestoneFor = node.id"
                class="mt-1 text-xs text-white/30 hover:text-white/60">+ milestone</button>

        <!-- Children (expanded) -->
        <template v-if="expandedGroups.has(node.id)">
          <div v-for="child in store.childrenOf(node.id)" :key="child.id"
               class="mt-2 ml-6 bg-white/5 border border-white/10 rounded-lg p-3">
            <div class="flex justify-between items-center mb-1">
              <template v-if="renaming === child.id">
                <input v-model="renameValue" @keyup.enter="saveRename" @keyup.escape="renaming = null"
                       class="flex-1 bg-transparent border-b border-white/40 text-sm outline-none" />
              </template>
              <h4 v-else class="font-medium text-sm truncate">
                {{ child.name }}
              </h4>
              <div class="flex gap-2 shrink-0">
                <button @click="startEdit(child.id)"
                        class="text-xs text-white/50 hover:text-white">Edit</button>
                <template v-if="renaming === child.id">
                  <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
                  <button @click="renaming = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
                </template>
                <button v-else @click="startRename(child.id, child.name)"
                        class="text-xs text-white/50 hover:text-white">Rename</button>
                <button @click="deleteWithConfirm(child)"
                        class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
              </div>
            </div>
            <div v-if="editing === child.id">
              <textarea v-model="editBody" rows="3"
                        class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
              <div class="flex gap-2 mt-2">
                <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
                <button @click="editing = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
              </div>
            </div>
            <p v-else class="text-xs text-white/50 line-clamp-2">{{ nodeBody(child.id) || '(empty)' }}</p>
          </div>

          <!-- Add sub-entry button -->
          <button @click="prefillSubEntry(node.name)"
                  class="mt-2 ml-6 text-xs text-white/40 hover:text-white/70">
            + Add sub-entry
          </button>
        </template>
      </div>
    </template>

    <div class="flex gap-2 mt-4">
      <input v-model="newSubject" placeholder="New name (or Parent/Child)..."
             class="flex-1 bg-white/5 border border-white/20 rounded px-3 py-2 text-sm outline-none focus:border-white/50" />
      <button @click="addEntry" class="bg-white/10 hover:bg-white/20 px-4 py-2 rounded text-sm">Add</button>
    </div>
  </div>
  <router-view />
  </div>
</template>
