<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAnchorStore, type Anchor } from '../stores/anchors'
import AnchorEditor from '../components/AnchorEditor.vue'

const anchorStore = useAnchorStore()
const pendingAnchor = ref<Omit<Anchor, 'id'> | null>(null)

onMounted(() => {
  anchorStore.fetchAnchors()
})

function addAnchor() {
  pendingAnchor.value = {
    name: '',
    time: '',
    duration_minutes: 60,
    flexibility: 'flexible',
    strictness: 3,
    color: '#888888',
    position: 0,
    followup_config: null,
  }
}

async function savePending(anchor: Anchor | Omit<Anchor, 'id'>) {
  await anchorStore.createAnchor(anchor as Omit<Anchor, 'id'>)
  pendingAnchor.value = null
}

function discardPending() {
  pendingAnchor.value = null
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
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold">Anchors</h2>
      <button v-if="!pendingAnchor" @click="addAnchor"
              class="px-4 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 rounded-lg text-sm">
        + Add Anchor
      </button>
    </div>
    <div class="flex flex-col gap-3">
      <!-- Pending new anchor at top -->
      <AnchorEditor
        v-if="pendingAnchor"
        :anchor="{ id: '__pending__', ...pendingAnchor }"
        :isPending="true"
        @save="savePending"
        @discard="discardPending" />

      <AnchorEditor
        v-for="anchor in anchorStore.anchors"
        :key="anchor.id"
        :anchor="anchor"
        @save="anchorStore.updateAnchor($event)"
        @delete="onDelete"
        @moveUp="onMoveUp"
        @moveDown="onMoveDown" />
    </div>
    <p v-if="!anchorStore.anchors.length && !pendingAnchor" class="text-[--fg-5] text-sm mt-4">
      No anchors yet. Add one to start building your schedule.
    </p>
  </div>
</template>
