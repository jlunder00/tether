<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useSuppressionsStore } from '../stores/suppressions'
import type { BeaconSuppression } from '../stores/suppressions'

const auth = useAuthStore()
const store = useSuppressionsStore()

// Beacon is premium-only. Treat absent is_paid as free.
const isPaid = computed(() => auth.user?.is_paid === true)

// ---------------------------------------------------------------------------
// Filter state (client-side; ready for backend filter params in Phase 5)
// ---------------------------------------------------------------------------

const CHECKPOINT_TYPES = [
  { label: 'All',               value: 'all' },
  { label: 'Anchor transition', value: 'anchor_transition' },
  { label: 'Task overdue',      value: 'task_overdue' },
  { label: 'Post-conversation', value: 'post_conversation' },
  { label: 'EOD',               value: 'eod' },
  { label: 'Other',             value: 'other' },
] as const

type CheckpointFilter = typeof CHECKPOINT_TYPES[number]['value']

const activeFilter = ref<CheckpointFilter>('all')

const filtered = computed<BeaconSuppression[]>(() => {
  if (activeFilter.value === 'all') return store.suppressions
  if (activeFilter.value === 'other') {
    const known = CHECKPOINT_TYPES
      .filter(t => t.value !== 'all' && t.value !== 'other')
      .map(t => t.value as string)
    return store.suppressions.filter(s => !known.includes(s.checkpoint_type ?? ''))
  }
  return store.suppressions.filter(s => s.checkpoint_type === activeFilter.value)
})

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

onMounted(() => {
  if (isPaid.value) {
    store.fetch()
  }
})
</script>

<template>
  <div class="max-w-2xl mx-auto px-4 py-8">
    <h1 class="text-xl font-semibold text-[--fg-1] mb-1">Suppression History</h1>
    <p class="text-sm text-[--fg-3] mb-6">
      Events Beacon chose not to notify you about.
    </p>

    <!-- Upgrade nudge: shown to free users -->
    <div
      v-if="!isPaid"
      class="rounded-xl border border-[--border-1] bg-[--bg-elev-1] px-6 py-8 text-center"
    >
      <p class="text-2xl mb-3">🔒</p>
      <h2 class="font-semibold text-[--fg-1] mb-2">Beacon is a premium feature</h2>
      <p class="text-sm text-[--fg-3] mb-4">
        Upgrade to a paid plan to unlock Beacon's intelligent notification system and
        see its suppression history.
      </p>
      <a
        href="/settings"
        class="inline-flex items-center px-4 py-2 rounded-lg bg-[--accent] text-[--accent-fg] text-sm font-medium hover:opacity-90 transition-opacity"
      >
        View upgrade options
      </a>
    </div>

    <!-- Paid user content -->
    <template v-else>

      <!-- Filter chips by checkpoint type -->
      <div class="flex flex-wrap gap-1.5 mb-5" aria-label="Filter by checkpoint type">
        <button
          v-for="chip in CHECKPOINT_TYPES"
          :key="chip.value"
          type="button"
          :data-testid="`filter-chip-${chip.value}`"
          :aria-pressed="activeFilter === chip.value ? 'true' : 'false'"
          class="text-xs px-3 py-1 rounded-full border transition-colors"
          :class="activeFilter === chip.value
            ? 'bg-[--accent] text-[--accent-fg] border-[--accent]'
            : 'bg-[--bg-2] text-[--fg-3] border-[--border-1] hover:bg-[--bg-3]'"
          @click="activeFilter = chip.value"
        >
          {{ chip.label }}
        </button>
      </div>

      <!-- Loading — skeleton items -->
      <ul
        v-if="store.loading"
        class="space-y-2"
        aria-busy="true"
        aria-label="Loading suppressions"
      >
        <li
          v-for="n in 4"
          :key="n"
          :data-testid="`skeleton-item-${n}`"
          class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-3 animate-pulse"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="h-3 w-40 rounded bg-[--bg-3]" />
            <div class="h-3 w-16 rounded bg-[--bg-3] flex-shrink-0" />
          </div>
          <div class="h-2.5 w-60 rounded bg-[--bg-3] mt-2" />
        </li>
      </ul>

      <!-- Error -->
      <div
        v-else-if="store.error"
        class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-4 text-sm text-[--fg-3]"
      >
        Could not load suppression history. {{ store.error }}
      </div>

      <!-- Empty state (no suppressions at all) -->
      <div
        v-else-if="store.suppressions.length === 0"
        data-testid="empty-state"
        class="rounded-xl border border-dashed border-[--border-2] bg-[--bg-elev-1] px-6 py-12 text-center"
      >
        <p class="text-3xl mb-3">🔕</p>
        <h2 class="font-medium text-[--fg-2] mb-2">No suppressed events yet</h2>
        <p class="text-sm text-[--fg-4] max-w-sm mx-auto leading-relaxed">
          When Beacon decides not to send you a notification — because you're
          already active, because you posted recently, or because it applied a
          cooldown — it logs the decision here so you can see what it filtered
          out and why.
        </p>
      </div>

      <!-- Filtered empty state (suppressions exist but current filter hides them all) -->
      <div
        v-else-if="filtered.length === 0"
        class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-6 text-center text-sm text-[--fg-4]"
      >
        No suppressions match this filter.
        <button
          type="button"
          class="ml-1 text-[--accent] hover:underline"
          @click="activeFilter = 'all'"
        >
          Clear filter
        </button>
      </div>

      <!-- Suppression list (shown when backend ships data) -->
      <ul v-else class="space-y-2">
        <li
          v-for="s in filtered"
          :key="s.id"
          class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-3 text-sm"
        >
          <div class="flex items-start justify-between gap-2">
            <!-- scope_key — monospaced for readability -->
            <span class="text-[--fg-2] font-mono text-xs truncate">{{ s.scope_key }}</span>
            <div class="flex items-center gap-2 flex-shrink-0">
              <span class="text-[--fg-5] text-xs">{{ s.source }}</span>
              <span class="text-[--fg-6] text-xs">{{ formatRelative(s.created_at) }}</span>
            </div>
          </div>
          <p v-if="s.reason" class="text-[--fg-3] mt-1 text-xs">{{ s.reason }}</p>
          <!-- Expiry note if set -->
          <p v-if="s.expires_at" class="text-[--fg-5] mt-0.5 text-xs italic">
            Expires {{ formatRelative(s.expires_at) }}
          </p>
        </li>
      </ul>
    </template>
  </div>
</template>
