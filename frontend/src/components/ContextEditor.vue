<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useContextStore } from '../stores/context'
import { useMilestoneStore } from '../stores/milestones'
import { useAutoScrollDrag } from '../composables/useAutoScrollDrag'
import ContextTreeNode from './ContextTreeNode.vue'

const contextStore = useContextStore()
const milestoneStore = useMilestoneStore()
const { onDragOver: autoScrollDragOver, cleanup: autoScrollCleanup } = useAutoScrollDrag()
const error = ref<string | null>(null)
const newName = ref('')
const rootDropOver = ref(false)

function onRootDragOver(evt: DragEvent) {
  evt.preventDefault()
  evt.dataTransfer!.dropEffect = 'move'
  rootDropOver.value = true
}

function onRootDragLeave() {
  rootDropOver.value = false
}

async function onRootDrop(evt: DragEvent) {
  evt.preventDefault()
  evt.stopPropagation()
  rootDropOver.value = false
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const { nodeId } = JSON.parse(raw)
    if (!nodeId) return
    await contextStore.moveNode(nodeId, null)
  } catch (e) {
    console.error('Root drop failed:', e)
    error.value = e instanceof Error ? e.message : 'Failed to move node to root'
  }
}

async function addRootNode() {
  if (!newName.value.trim()) return
  try {
    error.value = null
    await contextStore.createNode(null, newName.value.trim())
    await contextStore.fetchRootNodes()
    newName.value = ''
  } catch (e) {
    console.error('addRootNode error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to add entry'
  }
}

/** Load details sections for all root context nodes (for display bodies) */
async function loadRootSections() {
  const nodes = contextStore.rootContextNodes
  await Promise.allSettled(nodes.map(n => contextStore.fetchSection(n.id, 'details')))
}

watch(() => contextStore.showArchived, async () => {
  try {
    error.value = null
    await contextStore.fetchRootNodes()
    await loadRootSections()
  } catch (e) {
    console.error('showArchived toggle error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to reload context data'
  }
})

onMounted(async () => {
  try {
    await contextStore.fetchRootNodes()
    await loadRootSections()
    await milestoneStore.fetchAll()
  } catch (e) {
    console.error('ContextEditor mount error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to load context data'
  }
})
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6"
       @dragover="autoScrollDragOver"
       @drop="autoScrollCleanup">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">Context</h2>
      <label class="flex items-center gap-1.5 text-xs text-[--fg-4] hover:text-[--fg-2] cursor-pointer select-none">
        <input type="checkbox" v-model="contextStore.showArchived"
               class="accent-blue-500 w-3.5 h-3.5" />
        Show archived
      </label>
    </div>
    <p v-if="error" class="text-[--status-block-fg] text-sm mb-2">{{ error }}</p>

    <div class="flex flex-col gap-3">
      <ContextTreeNode
        v-for="node in contextStore.rootContextNodes"
        :key="node.id"
        :node="node"
        :depth="0" />
    </div>

    <!-- Root-level drop zone for reparenting nodes to root -->
    <div class="mt-3 border-2 border-dashed rounded-lg px-4 py-2 text-center text-xs transition-colors"
         :class="rootDropOver ? 'border-[--accent] bg-[--accent-veil] text-[--accent]' : 'border-[--border-1] text-[--fg-5]'"
         @dragover="onRootDragOver"
         @dragleave="onRootDragLeave"
         @drop="onRootDrop">
      Drop here to make root-level
    </div>

    <!-- Add root entry form -->
    <div class="mt-4 flex gap-2">
      <input v-model="newName" placeholder="New context entry name..."
             class="flex-1 bg-[--bg-input] text-[--fg-1] border border-[--border-input] rounded-lg px-3 py-2 outline-none focus:border-[--accent]"
             @keyup.enter="addRootNode" />
      <button @click="addRootNode" class="px-4 py-2 bg-[--accent-veil] text-[--accent] rounded-lg text-sm hover:bg-[--accent-soft]">
        + Add
      </button>
    </div>

    <router-view />
  </div>
</template>
