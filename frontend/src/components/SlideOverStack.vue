<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useSlideOver } from '../composables/useSlideOver'
import TaskDetailPanel from './TaskDetailPanel.vue'
import MilestoneDetailPanel from './MilestoneDetailPanel.vue'

const { stack, pop, close, restoreFromUrl } = useSlideOver()

const hasAnyPanel = computed(() => stack.value.length > 0)

// Each panel behind the top one is slightly offset, dimmed, and non-interactive.
function panelStyle(index: number) {
  const depth = stack.value.length - 1 - index
  const isTop = depth === 0
  return {
    transform: isTop ? 'translateX(0)' : `translateX(-${depth * 16}px)`,
    pointerEvents: isTop ? 'auto' : 'none',
    filter: isTop ? 'none' : 'brightness(0.6)',
    zIndex: 50 + index,
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && hasAnyPanel.value) pop()
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  restoreFromUrl()
})
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <!-- Dimmer — only behind the topmost panel -->
    <Transition name="fade">
      <div
        v-if="hasAnyPanel"
        class="fixed inset-0 z-40 bg-black/40"
        @click="pop"
      />
    </Transition>

    <!-- Stack of panels -->
    <TransitionGroup name="slide-over">
      <div
        v-for="(panel, index) in stack"
        :key="panel.id"
        class="fixed top-0 right-0 z-50 h-full w-full sm:w-[480px] lg:w-[520px] bg-gray-900 border-l border-white/10 shadow-2xl overflow-y-auto"
        :style="panelStyle(index)"
      >
        <!-- Back button / close -->
        <div class="flex items-center gap-2 px-4 py-3 border-b border-white/10 flex-shrink-0">
          <button
            v-if="index > 0"
            class="text-white/50 hover:text-white transition-colors text-sm mr-1"
            title="Back"
            @click="pop"
          >
            ← Back
          </button>
          <div class="flex-1" />
          <button
            class="text-white/30 hover:text-white transition-colors p-1 rounded hover:bg-white/10"
            title="Close all (Esc)"
            @click="close"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Panel content — routed by kind -->
        <TaskDetailPanel
          v-if="panel.kind === 'task' || panel.kind === 'event'"
          :task-id="panel.entityId"
        />
        <MilestoneDetailPanel
          v-else-if="panel.kind === 'milestone'"
          :milestone-id="panel.entityId"
        />
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
/* Dimmer fade */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Panel slide */
.slide-over-enter-active,
.slide-over-leave-active {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.slide-over-enter-from,
.slide-over-leave-to {
  transform: translateX(100%) !important;
  opacity: 0;
}
</style>
