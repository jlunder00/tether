<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useContextStore } from '../stores/context'
import { useMilestoneStore } from '../stores/milestones'
import ContextTreeNode from './ContextTreeNode.vue'

const contextStore = useContextStore()
const milestoneStore = useMilestoneStore()
const error = ref<string | null>(null)
const newName = ref('')

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
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h2 class="text-lg font-semibold mb-4">Context</h2>
    <p v-if="error" class="text-red-400 text-sm mb-2">{{ error }}</p>

    <div class="flex flex-col gap-3">
      <ContextTreeNode
        v-for="node in contextStore.rootContextNodes"
        :key="node.id"
        :node="node"
        :depth="0" />
    </div>

    <!-- Add root entry form -->
    <div class="mt-4 flex gap-2">
      <input v-model="newName" placeholder="New context entry name..."
             class="flex-1 bg-white/10 text-white rounded-lg px-3 py-2 outline-none"
             @keyup.enter="addRootNode" />
      <button @click="addRootNode" class="px-4 py-2 bg-blue-500/20 text-blue-300 rounded-lg text-sm">
        + Add
      </button>
    </div>

    <router-view />
  </div>
</template>
