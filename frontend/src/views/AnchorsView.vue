<script setup lang="ts">
import { onMounted } from 'vue'
import { useAnchorStore } from '../stores/anchors'
import AnchorEditor from '../components/AnchorEditor.vue'

const anchorStore = useAnchorStore()

onMounted(() => {
  anchorStore.fetchAnchors()
})

async function addAnchor() {
  const position = anchorStore.anchors.length
  await anchorStore.createAnchor({
    name: 'New Block',
    time: '09:00',
    duration_minutes: 60,
    flexibility: 'flexible',
    strictness: 3,
    color: '#888888',
    position,
    followup_config: null,
  })
}

async function onDelete(anchorId: string) {
  await anchorStore.deleteAnchor(anchorId)
}

async function onMoveUp(anchorId: string) {
  const idx = anchorStore.anchors.findIndex(a => a.id === anchorId)
  if (idx <= 0) return
  const a = anchorStore.anchors[idx]
  const b = anchorStore.anchors[idx - 1]
  await anchorStore.updateAnchor({ ...a, position: b.position })
  await anchorStore.updateAnchor({ ...b, position: a.position })
}

async function onMoveDown(anchorId: string) {
  const idx = anchorStore.anchors.findIndex(a => a.id === anchorId)
  if (idx < 0 || idx >= anchorStore.anchors.length - 1) return
  const a = anchorStore.anchors[idx]
  const b = anchorStore.anchors[idx + 1]
  await anchorStore.updateAnchor({ ...a, position: b.position })
  await anchorStore.updateAnchor({ ...b, position: a.position })
}
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">Anchors</h2>
      <button @click="addAnchor"
              class="px-4 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 rounded-lg text-sm">
        + Add Anchor
      </button>
    </div>
    <div class="flex flex-col gap-3">
      <AnchorEditor
        v-for="anchor in anchorStore.anchors"
        :key="anchor.id"
        :anchor="anchor"
        @save="anchorStore.updateAnchor($event)"
        @delete="onDelete"
        @moveUp="onMoveUp"
        @moveDown="onMoveDown" />
    </div>
    <p v-if="!anchorStore.anchors.length" class="text-white/30 text-sm mt-4">
      No anchors yet. Add one to start building your schedule.
    </p>
  </div>
</template>
