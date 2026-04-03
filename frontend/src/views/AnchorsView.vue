<script setup lang="ts">
import { onMounted } from 'vue'
import { useAnchorStore } from '../stores/anchors'
import AnchorEditor from '../components/AnchorEditor.vue'

const anchorStore = useAnchorStore()

onMounted(() => {
  anchorStore.fetchAnchors()
})
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
    <h2 class="text-lg font-semibold mb-4">Anchors</h2>
    <div class="flex flex-col gap-3">
      <AnchorEditor
        v-for="anchor in anchorStore.anchors"
        :key="anchor.id"
        :anchor="anchor"
        @save="anchorStore.updateAnchor($event)" />
    </div>
  </div>
</template>
