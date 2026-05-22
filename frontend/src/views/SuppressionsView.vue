<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useSuppressionsStore } from '../stores/suppressions'

const auth = useAuthStore()
const store = useSuppressionsStore()

// Beacon is premium-only. Treat absent is_paid as free.
const isPaid = computed(() => auth.user?.is_paid === true)

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
      <!-- Loading -->
      <div v-if="store.loading" class="text-sm text-[--fg-4] py-8 text-center">
        Loading…
      </div>

      <!-- Error -->
      <div
        v-else-if="store.error"
        class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-4 text-sm text-[--fg-3]"
      >
        Could not load suppression history. {{ store.error }}
      </div>

      <!-- Empty state -->
      <div
        v-else-if="store.suppressions.length === 0"
        class="rounded-xl border border-dashed border-[--border-2] bg-[--bg-elev-1] px-6 py-12 text-center"
      >
        <p class="text-3xl mb-3">🔕</p>
        <h2 class="font-medium text-[--fg-2] mb-1">No suppressed events yet</h2>
        <p class="text-sm text-[--fg-4]">
          When Beacon decides not to notify you about something, it will appear here
          so you can see what it filtered out.
        </p>
      </div>

      <!-- Suppression list (shown once backend ships) -->
      <ul v-else class="space-y-2">
        <li
          v-for="s in store.suppressions"
          :key="s.id"
          class="rounded-lg border border-[--border-1] bg-[--bg-elev-1] px-4 py-3 text-sm"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="text-[--fg-2] font-mono text-xs">{{ s.scope_key }}</span>
            <span class="text-[--fg-5] text-xs flex-shrink-0">{{ s.source }}</span>
          </div>
          <p v-if="s.reason" class="text-[--fg-3] mt-1">{{ s.reason }}</p>
        </li>
      </ul>
    </template>
  </div>
</template>
