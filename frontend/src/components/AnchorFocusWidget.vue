<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAnchorStore, computeAnchorStates } from '../stores/anchors'
import type { Anchor } from '../stores/anchors'

const anchorStore = useAnchorStore()

// Reactive clock — widget auto-shifts as anchors change
const now = ref(new Date())
let clockTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  clockTimer = setInterval(() => { now.value = new Date() }, 60_000)
})
onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})

const sorted = computed<Anchor[]>(() =>
  [...anchorStore.anchors].sort((a, b) => a.time.localeCompare(b.time))
)

const states = computed(() => computeAnchorStates(sorted.value, now.value))

const currentIndex = computed(() =>
  sorted.value.findIndex(a => states.value.get(a.id) === 'now')
)

const prevAnchor = computed<Anchor | null>(() =>
  currentIndex.value > 0 ? sorted.value[currentIndex.value - 1] : null
)
const currentAnchor = computed<Anchor | null>(() =>
  currentIndex.value >= 0 ? sorted.value[currentIndex.value] : null
)
const nextAnchor = computed<Anchor | null>(() =>
  currentIndex.value >= 0 && currentIndex.value < sorted.value.length - 1
    ? sorted.value[currentIndex.value + 1]
    : null
)
</script>

<template>
  <div class="anchor-focus-widget" data-testid="anchor-focus-widget">
    <!-- Previous anchor -->
    <div
      v-if="prevAnchor"
      data-testid="anchor-focus-prev"
      class="anchor-focus-row anchor-focus-row--subdued"
    >
      <div
        class="anchor-focus-dot anchor-focus-dot--past"
        :style="prevAnchor.motif ? { background: `var(--motif-${prevAnchor.motif})` } : {}"
      />
      <div class="anchor-focus-content">
        <span class="anchor-focus-name">{{ prevAnchor.name }}</span>
        <span class="anchor-focus-time">{{ prevAnchor.time }}</span>
      </div>
    </div>

    <!-- Current anchor -->
    <div
      v-if="currentAnchor"
      data-testid="anchor-focus-current"
      class="anchor-focus-row anchor-focus-row--current"
    >
      <div
        class="anchor-focus-dot anchor-focus-dot--now"
        :style="currentAnchor.motif
          ? {
              background: `var(--motif-${currentAnchor.motif})`,
              boxShadow: `0 0 0 4px var(--bg-canvas), 0 0 0 6px var(--motif-${currentAnchor.motif}-veil, var(--line-glow))`,
            }
          : {}"
      />
      <div class="anchor-focus-content">
        <div class="anchor-focus-name-row">
          <span class="anchor-focus-name anchor-focus-name--current">{{ currentAnchor.name }}</span>
          <span class="anchor-focus-badge">now</span>
        </div>
        <span class="anchor-focus-time">{{ currentAnchor.time }}</span>
      </div>
    </div>

    <!-- Next anchor -->
    <div
      v-if="nextAnchor"
      data-testid="anchor-focus-next"
      class="anchor-focus-row anchor-focus-row--subdued"
    >
      <div
        class="anchor-focus-dot anchor-focus-dot--upcoming"
        :style="nextAnchor.motif ? { background: `var(--motif-${nextAnchor.motif})` } : {}"
      />
      <div class="anchor-focus-content">
        <span class="anchor-focus-name">{{ nextAnchor.name }}</span>
        <span class="anchor-focus-time">{{ nextAnchor.time }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.anchor-focus-widget {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.anchor-focus-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.anchor-focus-row--subdued {
  opacity: 0.5;
}

.anchor-focus-row--current {
  opacity: 1;
}

/* Dots */
.anchor-focus-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--line-color);
}

.anchor-focus-dot--now {
  width: 12px;
  height: 12px;
  background: var(--node-now);
  box-shadow:
    0 0 0 3px var(--bg-canvas),
    0 0 0 5px var(--line-glow);
}

.anchor-focus-dot--past {
  background: var(--node-done);
  opacity: 0.6;
}

.anchor-focus-dot--upcoming {
  background: var(--node-fill);
  border: 1.5px solid var(--line-color);
}

/* Content */
.anchor-focus-content {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.anchor-focus-name-row {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.anchor-focus-name {
  font-size: 12px;
  color: var(--fg-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.anchor-focus-name--current {
  font-size: 16px;
  font-weight: 600;
  color: var(--fg-1);
  letter-spacing: -0.01em;
}

.anchor-focus-badge {
  font-family: "JetBrains Mono", monospace;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  padding: 2px 5px;
  border-radius: 2px;
  background: var(--node-now);
  color: var(--bg-canvas);
  flex-shrink: 0;
}

.anchor-focus-time {
  font-family: "JetBrains Mono", monospace;
  font-size: 10px;
  color: var(--fg-4);
}
</style>
