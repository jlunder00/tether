<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useContextStore } from '../stores/context'
import type { ContextNode, SectionFileInfo } from '../stores/context'
import { api } from '../lib/api'
import ContextTreeNode from './ContextTreeNode.vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import { useSlideOver } from '../composables/useSlideOver'

const props = withDefaults(defineProps<{
  node: ContextNode
  depth?: number
}>(), {
  depth: 0,
})

const contextStore = useContextStore()
const { push: pushPanel } = useSlideOver()

// --- Local state (per-instance) ---
const expanded = ref(false)
const activeTab = ref<string>('details')
const activeFileName = ref<string>('main')
const sectionFiles = ref<SectionFileInfo[]>([])
const editingSection = ref<string | null>(null)
const editBody = ref('')
const renaming = ref(false)
const renameValue = ref('')
const error = ref<string | null>(null)
const addingChild = ref(false)
const newChildName = ref('')
const showAddSection = ref(false)
const newSectionName = ref('')
const localSectionTypes = ref<string[]>([])
const dragOver = ref(false)
const newChildType = ref<'context' | 'milestone'>('context')
const newChildTargetDate = ref('')
const newChildColor = ref('#3b82f6')
const editingDescription = ref(false)
const descriptionDraft = ref('')
const addingFile = ref(false)
const newFileName = ref('')
const nodeTasks = ref<any[]>([])
const loadingTasks = ref(false)

// --- Tasks tab constants ---
const TASK_STATUS_ORDER = ['in_progress', 'pending', 'blocked', 'done', 'skipped']
const TASK_STATUS_LABELS: Record<string, string> = {
  in_progress: 'In Progress', pending: 'Pending', blocked: 'Blocked',
  done: 'Done', skipped: 'Skipped',
}
const TASK_STATUS_COLORS: Record<string, string> = {
  in_progress: '#f59e0b', pending: '#3b82f6', blocked: '#ef4444',
  done: '#22c55e', skipped: '#94a3b8',
}

// --- Computed ---
const children = computed(() => contextStore.childrenOf(props.node.id))
const hasChildren = computed(() =>
  children.value.length > 0 || props.node.children_count == null || props.node.children_count > 0
)
const nodeBody = computed(() => contextStore.sectionCache[`${props.node.id}::details::main`]?.body ?? '')

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-white/20', in_progress: 'bg-blue-400',
  done: 'bg-green-400', blocked: 'bg-red-400',
}

const allSectionTypes = computed(() => {
  const defaults = ['details', 'plans', 'notes']
  const fromNode = props.node.section_types ?? []
  const local = localSectionTypes.value
  return [...new Set([...defaults, ...fromNode, ...local])]
})

const activeBody = computed(() => {
  const key = `${props.node.id}::${activeTab.value}::${activeFileName.value}`
  return contextStore.sectionCache[key]?.body ?? ''
})

const collapsedPreview = computed(() => {
  if (props.node.description) return props.node.description
  return nodeBody.value || '(empty)'
})

const taskGroups = computed(() => {
  return TASK_STATUS_ORDER
    .map(status => ({
      status,
      label: TASK_STATUS_LABELS[status],
      color: TASK_STATUS_COLORS[status],
      tasks: nodeTasks.value.filter(t => t.status === status),
    }))
    .filter(g => g.tasks.length > 0)
})

const PROGRESS_BAR_SEGMENTS = [
  { status: 'done', color: '#22c55e' },
  { status: 'in_progress', color: '#3b82f6' },
  { status: 'pending', color: 'rgba(255,255,255,0.15)' },
  { status: 'blocked', color: '#ef4444' },
  { status: 'skipped', color: '#94a3b8' },
]

const taskStatusCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const t of nodeTasks.value) {
    counts[t.status] = (counts[t.status] || 0) + 1
  }
  return counts
})

const tasksDoneCount = computed(() => nodeTasks.value.filter(t => t.status === 'done').length)
const tasksTotalCount = computed(() => nodeTasks.value.length)
const tasksProgressPct = computed(() =>
  tasksTotalCount.value > 0 ? Math.round((tasksDoneCount.value / tasksTotalCount.value) * 100) : 0
)

const depthStyle = computed(() => ({
  paddingLeft: props.depth * 16 + 'px',
}))

const cardStyle = computed(() => {
  const base: Record<string, string> = {
    backgroundColor: 'rgba(255,255,255,' + (0.03 + props.depth * 0.01) + ')',
  }
  if (props.node.node_type === 'milestone' && props.node.color) {
    base.borderLeftColor = props.node.color
    base.borderLeftWidth = '3px'
  }
  return base
})

// --- Drag & Drop ---

function onDragStart(evt: DragEvent) {
  evt.dataTransfer!.effectAllowed = 'move'
  evt.dataTransfer!.setData('text/plain', JSON.stringify({ nodeId: props.node.id }))
}

function onDragOver(evt: DragEvent) {
  evt.preventDefault()
  evt.dataTransfer!.dropEffect = 'move'
  dragOver.value = true
}

function onDragLeave() {
  dragOver.value = false
}

async function onDrop(evt: DragEvent) {
  evt.preventDefault()
  evt.stopPropagation()
  dragOver.value = false
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const { nodeId } = JSON.parse(raw)
    if (!nodeId || nodeId === props.node.id) return
    await contextStore.moveNode(nodeId, props.node.id)
  } catch (e) {
    console.error('Drop failed:', e)
    error.value = e instanceof Error ? e.message : 'Failed to move node'
  }
}

// --- Actions ---

// Re-fetch children when "Show archived" toggles while this node is expanded
watch(() => contextStore.showArchived, async () => {
  if (!expanded.value) return
  try {
    await contextStore.fetchChildren(props.node.id)
  } catch (e) {
    console.error('showArchived re-fetch error:', e)
  }
})

async function toggleExpand() {
  if (expanded.value) {
    expanded.value = false
    return
  }
  expanded.value = true
  try {
    error.value = null
    const fetched = await contextStore.fetchChildren(props.node.id)
    await Promise.allSettled(fetched.map(c => contextStore.fetchSection(c.id, 'details', 'main')))
    // Fetch file list for the active tab and load the active file
    if (activeTab.value === 'tasks') {
      await fetchNodeTasks()
    } else {
      await loadTabFiles(activeTab.value)
      if (props.node.node_type === 'milestone') {
        fetchNodeTasks()  // fire-and-forget for header progress bar
      }
    }
  } catch (e) {
    expanded.value = false
    console.error('toggleExpand error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to expand node'
  }
}

async function loadTabFiles(sectionType: string) {
  try {
    const files = await contextStore.fetchSectionFiles(props.node.id, sectionType)
    sectionFiles.value = files
    // Pick active file: prefer current activeFileName if it exists, else first file, else 'main'
    const match = files.find(f => f.name === activeFileName.value)
    if (!match && files.length > 0) {
      activeFileName.value = files[0].name
    } else if (!match) {
      activeFileName.value = 'main'
    }
    // Fetch the body for the active file
    const key = `${props.node.id}::${sectionType}::${activeFileName.value}`
    if (!contextStore.sectionCache[key]) {
      await contextStore.fetchSection(props.node.id, sectionType, activeFileName.value)
    }
  } catch (e) {
    // If the section type has no files yet, that's OK
    sectionFiles.value = []
    activeFileName.value = 'main'
    console.error('loadTabFiles error:', e)
  }
}

async function fetchNodeTasks() {
  try {
    loadingTasks.value = true
    error.value = null
    const resp = await api(`/api/nodes/${props.node.id}/tasks`)
    if (!resp.ok) {
      const detail = await resp.text().catch(() => '')
      throw new Error(`fetchNodeTasks: ${resp.status} ${detail}`)
    }
    nodeTasks.value = await resp.json()
  } catch (e) {
    console.error('fetchNodeTasks error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to fetch tasks'
    // Don't clear nodeTasks — stale data is better than showing "(no linked tasks)" after a fetch failure
  } finally {
    loadingTasks.value = false
  }
}

async function switchTab(sectionType: string) {
  activeTab.value = sectionType
  editingSection.value = null
  activeFileName.value = 'main'
  addingFile.value = false
  if (sectionType === 'tasks') {
    await fetchNodeTasks()
  } else {
    await loadTabFiles(sectionType)
  }
}

async function selectFile(fileName: string) {
  activeFileName.value = fileName
  editingSection.value = null
  const key = `${props.node.id}::${activeTab.value}::${fileName}`
  if (!contextStore.sectionCache[key]) {
    try {
      await contextStore.fetchSection(props.node.id, activeTab.value, fileName)
    } catch (e) {
      console.error('selectFile fetch error:', e)
      error.value = e instanceof Error ? e.message : 'Failed to load file'
    }
  }
}

async function startEdit() {
  editingSection.value = activeTab.value
  try {
    const section = await contextStore.fetchSection(props.node.id, activeTab.value, activeFileName.value)
    editBody.value = section?.body ?? ''
  } catch (e) {
    editingSection.value = null
    console.error('startEdit error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to load section'
  }
}

async function saveEdit() {
  if (!editingSection.value) return
  try {
    error.value = null
    await contextStore.saveSection(props.node.id, editingSection.value, editBody.value, activeFileName.value)
    editingSection.value = null
    // Refresh file list to get updated size
    await loadTabFiles(activeTab.value)
  } catch (e) {
    console.error('saveEdit error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to save'
  }
}

async function addSection() {
  const name = newSectionName.value.trim().toLowerCase()
  if (!name) return
  if (allSectionTypes.value.includes(name)) {
    // Section type already exists, just switch to it
    showAddSection.value = false
    newSectionName.value = ''
    await switchTab(name)
    return
  }
  try {
    error.value = null
    await contextStore.createSectionFile(props.node.id, name, 'main', '')
    localSectionTypes.value.push(name)
    showAddSection.value = false
    newSectionName.value = ''
    activeTab.value = name
    activeFileName.value = 'main'
    await loadTabFiles(name)
  } catch (e) {
    console.error('addSection error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add section'
  }
}

async function addFile() {
  const name = newFileName.value.trim()
  if (!name) return
  // Check if file already exists in current tab
  if (sectionFiles.value.some(f => f.name === name)) {
    error.value = `File "${name}" already exists in ${activeTab.value}`
    return
  }
  try {
    error.value = null
    await contextStore.createSectionFile(props.node.id, activeTab.value, name, '')
    addingFile.value = false
    newFileName.value = ''
    activeFileName.value = name
    await loadTabFiles(activeTab.value)
  } catch (e) {
    console.error('addFile error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add file'
  }
}

async function deleteFile(fileName: string) {
  if (!confirm(`Delete file "${fileName}" from ${activeTab.value}?`)) return
  try {
    error.value = null
    await contextStore.deleteSectionFile(props.node.id, activeTab.value, fileName)
    await loadTabFiles(activeTab.value)
  } catch (e) {
    console.error('deleteFile error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to delete file'
  }
}

function startDescriptionEdit() {
  editingDescription.value = true
  descriptionDraft.value = props.node.description ?? ''
}

async function saveDescription() {
  try {
    error.value = null
    await contextStore.patchNode(props.node.id, { description: descriptionDraft.value || null })
    editingDescription.value = false
  } catch (e) {
    console.error('saveDescription error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to save description'
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

async function setArchived(archived: boolean) {
  try {
    error.value = null
    await contextStore.patchNode(props.node.id, { archived })
  } catch (e) {
    console.error('setArchived error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to update archive status'
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
    const opts: { target_date?: string; color?: string } = {}
    if (newChildType.value === 'milestone') {
      if (newChildTargetDate.value) opts.target_date = newChildTargetDate.value
      if (newChildColor.value) opts.color = newChildColor.value
    }
    await contextStore.createNode(props.node.id, newChildName.value.trim(), newChildType.value, opts)
    newChildName.value = ''
    newChildType.value = 'context'
    newChildTargetDate.value = ''
    newChildColor.value = '#3b82f6'
    addingChild.value = false
    if (!expanded.value) expanded.value = true
  } catch (e) {
    console.error('addChild error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add child'
  }
}

</script>

<template>
  <div :style="depthStyle">
    <div class="border border-white/10 rounded-xl p-4 transition-shadow"
         :class="[dragOver ? 'ring-2 ring-blue-400/50' : '', node.archived ? 'opacity-50' : '']"
         :style="cardStyle"
         :draggable="true"
         @dragstart.stop="onDragStart"
         @dragover="onDragOver"
         @dragleave="onDragLeave"
         @drop="onDrop">
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
          <template v-else>
            <!-- Milestone color dot -->
            <span v-if="node.node_type === 'milestone'"
                  class="w-2 h-2 rounded-full shrink-0"
                  :class="node.color ? '' : (STATUS_COLORS[node.status ?? ''] ?? 'bg-white/20')"
                  :style="node.color ? { backgroundColor: node.color } : {}" />
            <h3 class="font-semibold text-sm truncate" :class="node.archived ? 'line-through text-white/40' : ''">{{ node.name }}</h3>
          </template>
          <!-- Milestone status badge -->
          <span v-if="node.node_type === 'milestone' && node.status"
                class="text-[9px] px-1.5 py-0.5 rounded shrink-0"
                :class="{
                  'bg-white/10 text-white/50': node.status === 'pending',
                  'bg-blue-500/20 text-blue-300': node.status === 'in_progress',
                  'bg-green-500/20 text-green-300': node.status === 'done',
                  'bg-red-500/20 text-red-300': node.status === 'blocked',
                }">
            {{ node.status.replace('_', ' ') }}
          </span>
          <!-- Milestone target date -->
          <span v-if="node.node_type === 'milestone' && node.target_date"
                class="text-[9px] text-white/40 shrink-0">
            {{ node.target_date }}
          </span>
          <span v-if="node.archived" class="text-[9px] px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-400/80 shrink-0">Archived</span>
        </div>

        <div class="flex gap-2 shrink-0">
          <button v-if="node.node_type === 'milestone'"
                  @click.stop="pushPanel({ kind: 'milestone', entityId: node.id })"
                  class="text-xs text-blue-400/60 hover:text-blue-400">Detail</button>
          <template v-if="renaming">
            <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
            <button @click="renaming = false" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
          </template>
          <button v-else @click="startRename"
                  class="text-xs text-white/50 hover:text-white">Rename</button>
          <button v-if="node.archived"
                  @click="setArchived(false)"
                  class="text-xs text-yellow-400/60 hover:text-yellow-400">Unarchive</button>
          <button v-else
                  @click="setArchived(true)"
                  class="text-xs text-white/40 hover:text-white/70">Archive</button>
          <button @click="deleteWithConfirm"
                  class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
        </div>
      </div>

      <!-- Segmented progress bar for milestones -->
      <div v-if="node.node_type === 'milestone' && tasksTotalCount > 0"
           class="flex h-1.5 rounded-full overflow-hidden mt-1">
        <div v-for="seg in PROGRESS_BAR_SEGMENTS"
             :key="seg.status"
             v-show="taskStatusCounts[seg.status]"
             :style="{ width: ((taskStatusCounts[seg.status] || 0) / tasksTotalCount * 100) + '%', backgroundColor: seg.color }" />
      </div>

      <!-- Collapsed: show description or details preview -->
      <p v-if="!expanded" class="text-xs text-white/50 line-clamp-2">{{ collapsedPreview }}</p>

      <!-- Expanded: description + section tabs + content -->
      <template v-if="expanded">
        <!-- Description area -->
        <div class="mb-2">
          <div v-if="editingDescription" class="flex flex-col gap-1">
            <textarea v-model="descriptionDraft" rows="2" placeholder="Node description..."
                      class="w-full bg-transparent border border-white/20 rounded p-2 text-xs outline-none focus:border-white/50 resize-none" />
            <div class="flex gap-2">
              <button @click="saveDescription" class="text-[10px] text-green-400/70 hover:text-green-400">Save</button>
              <button @click="editingDescription = false" class="text-[10px] text-white/40 hover:text-white/70">Cancel</button>
            </div>
          </div>
          <div v-else class="flex items-start gap-1">
            <p v-if="node.description" class="text-xs text-white/60 italic flex-1">{{ node.description }}</p>
            <p v-else class="text-xs text-white/30 italic flex-1">(no description)</p>
            <button @click="startDescriptionEdit"
                    class="text-[10px] text-white/30 hover:text-white/60 shrink-0">edit</button>
          </div>
        </div>

        <!-- Tab bar -->
        <div class="flex gap-1 mt-1 flex-wrap items-center">
          <button v-for="st in allSectionTypes" :key="st"
                  @click.stop="switchTab(st)"
                  class="text-[10px] px-2 py-0.5 rounded-full"
                  :class="activeTab === st ? 'bg-blue-500/30 text-blue-300' : 'bg-white/10 text-white/40 hover:bg-white/20'">
            {{ st }}
          </button>
          <button @click.stop="switchTab('tasks')"
                  class="text-[10px] px-2 py-0.5 rounded-full"
                  :class="activeTab === 'tasks' ? 'bg-blue-500/30 text-blue-300' : 'bg-white/10 text-white/40 hover:bg-white/20'">
            tasks
          </button>
          <div v-if="showAddSection" class="flex items-center gap-1">
            <input v-model="newSectionName" placeholder="section name..."
                   @keydown.enter="addSection"
                   @keydown.escape="showAddSection = false; newSectionName = ''"
                   class="bg-transparent border-b border-white/30 outline-none text-[10px] w-24" />
            <button @click="addSection" class="text-[10px] text-white/60 hover:text-white">add</button>
            <button @click="showAddSection = false; newSectionName = ''"
                    class="text-[10px] text-white/40">cancel</button>
          </div>
          <button v-else @click.stop="showAddSection = true"
                  class="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-white/30 hover:text-white/50">
            +
          </button>
        </div>

        <!-- Section file list + content (hidden when tasks tab active) -->
        <template v-if="activeTab !== 'tasks'">
          <!-- File list within active tab -->
          <div v-if="sectionFiles.length > 1 || addingFile" class="mt-1 flex gap-1 flex-wrap items-center">
            <button v-for="f in sectionFiles" :key="f.name"
                    @click.stop="selectFile(f.name)"
                    class="text-[10px] px-1.5 py-0.5 rounded border flex items-center gap-1 group"
                    :class="activeFileName === f.name
                      ? 'border-blue-400/40 bg-blue-500/15 text-blue-200'
                      : 'border-white/10 bg-white/5 text-white/40 hover:bg-white/10 hover:text-white/60'">
              {{ f.name }}
              <span class="text-white/20 text-[8px]">{{ f.size }}c</span>
              <span v-if="sectionFiles.length > 1"
                    @click.stop="deleteFile(f.name)"
                    class="text-red-400/0 group-hover:text-red-400/50 hover:!text-red-400 cursor-pointer ml-0.5"
                    title="Delete file">&times;</span>
            </button>
            <div v-if="addingFile" class="flex items-center gap-1">
              <input v-model="newFileName" placeholder="file name..."
                     @keydown.enter="addFile"
                     @keydown.escape="addingFile = false; newFileName = ''"
                     class="bg-transparent border-b border-white/30 outline-none text-[10px] w-20" />
              <button @click="addFile" class="text-[10px] text-white/60 hover:text-white">add</button>
              <button @click="addingFile = false; newFileName = ''"
                      class="text-[10px] text-white/40">cancel</button>
            </div>
            <button v-else @click.stop="addingFile = true"
                    class="text-[10px] px-1 py-0.5 text-white/25 hover:text-white/50">+ file</button>
          </div>
          <!-- If only one file (or none), just show a small add-file button -->
          <div v-else class="mt-1">
            <div v-if="addingFile" class="flex items-center gap-1">
              <input v-model="newFileName" placeholder="file name..."
                     @keydown.enter="addFile"
                     @keydown.escape="addingFile = false; newFileName = ''"
                     class="bg-transparent border-b border-white/30 outline-none text-[10px] w-20" />
              <button @click="addFile" class="text-[10px] text-white/60 hover:text-white">add</button>
              <button @click="addingFile = false; newFileName = ''"
                      class="text-[10px] text-white/40">cancel</button>
            </div>
            <button v-else @click.stop="addingFile = true"
                    class="text-[10px] text-white/25 hover:text-white/50">+ file</button>
          </div>

          <!-- Active tab content -->
          <div class="mt-2">
            <div v-if="editingSection === activeTab">
              <textarea v-model="editBody" rows="4"
                        class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
              <div class="flex gap-2 mt-2">
                <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
                <button @click="editingSection = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
              </div>
            </div>
            <div v-else>
              <p class="text-xs text-white/50 whitespace-pre-wrap">{{ activeBody || '(empty)' }}</p>
              <button @click="startEdit"
                      class="mt-1 text-xs text-white/40 hover:text-white/70">Edit {{ activeTab }}/{{ activeFileName }}</button>
            </div>
          </div>
        </template>

        <!-- Tasks tab content -->
        <div v-else class="mt-2">
          <!-- Milestone progress bar -->
          <div v-if="node.node_type === 'milestone' && tasksTotalCount > 0" class="mb-3">
            <div class="flex items-center justify-between mb-1">
              <span class="text-[10px] text-white/50">Progress</span>
              <span class="text-[10px] text-white/50">{{ tasksDoneCount }}/{{ tasksTotalCount }} ({{ tasksProgressPct }}%)</span>
            </div>
            <div class="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div class="h-full bg-green-500 rounded-full transition-all"
                   :style="{ width: tasksProgressPct + '%' }" />
            </div>
          </div>

          <div v-if="loadingTasks" class="text-xs text-white/40">Loading tasks...</div>
          <div v-else-if="nodeTasks.length === 0" class="text-xs text-white/40">(no linked tasks)</div>
          <div v-else class="flex flex-col gap-2">
            <GroupContainer
              v-for="group in taskGroups"
              :key="group.status"
              :label="`${group.label} (${group.tasks.length})`"
              :color="group.color"
              :level="1"
              :collapsible="true">
              <div class="flex flex-col gap-1.5">
                <TaskCard
                  v-for="t in group.tasks"
                  :key="t.id"
                  :task="t"
                  :compact="true"
                  :editable="false"
                  :showRemove="false"
                  :hideTags="false"
                  :navigable="false" />
              </div>
            </GroupContainer>
          </div>
        </div>
      </template>

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
        <div v-if="addingChild" class="mt-2 flex flex-wrap gap-2 items-center" :style="{ paddingLeft: (depth + 1) * 16 + 'px' }">
          <input v-model="newChildName" placeholder="New child name..."
                 @keyup.enter="addChild"
                 @keyup.escape="addingChild = false; newChildType = 'context'; newChildTargetDate = ''; newChildColor = '#3b82f6'"
                 class="flex-1 bg-transparent border-b border-white/30 outline-none text-xs min-w-[120px]" />
          <select v-model="newChildType" class="bg-white/10 text-white text-xs rounded px-1 py-0.5">
            <option value="context">Context</option>
            <option value="milestone">Milestone</option>
          </select>
          <template v-if="newChildType === 'milestone'">
            <input v-model="newChildTargetDate" type="date" class="bg-white/10 text-white text-xs rounded px-2 py-0.5" />
            <input v-model="newChildColor" type="color" class="w-6 h-6 rounded cursor-pointer" />
          </template>
          <button @click="addChild" class="text-xs text-white/60 hover:text-white">Add</button>
          <button @click="addingChild = false; newChildName = ''; newChildType = 'context'; newChildTargetDate = ''; newChildColor = '#3b82f6'"
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
