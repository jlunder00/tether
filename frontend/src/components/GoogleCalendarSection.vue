<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useIntegrationsStore } from '../stores/integrations'

const store = useIntegrationsStore()

// Tick every 30s so the "Last synced X ago" caption stays fresh.
const now = ref(Date.now())
let tickHandle: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchGCalStatus()
  tickHandle = setInterval(() => {
    now.value = Date.now()
  }, 30_000)
})

onUnmounted(() => {
  if (tickHandle !== null) clearInterval(tickHandle)
})

function formatRelative(iso: string, currentMs: number): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const diffSec = Math.max(0, Math.round((currentMs - then) / 1000))
  if (diffSec < 5) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.round(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.round(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.round(diffHr / 24)
  return `${diffDay}d ago`
}

const lastSyncedLabel = computed(() => {
  if (!store.lastSyncedAt) return null
  return formatRelative(store.lastSyncedAt, now.value)
})
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Google Calendar</h2>
    <div class="bg-[--bg-elev-1] rounded-xl p-4">
      <!-- Status row -->
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2">
          <!-- Google Calendar icon -->
          <svg class="w-5 h-5 flex-shrink-0" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
          </svg>
          <div>
            <div class="text-sm font-medium text-[--fg-1]">Google Calendar</div>
            <div v-if="store.gcalConnected" class="text-xs text-[--status-done-fg] flex items-center gap-1">
              <span>✓</span>
              <span>Connected</span>
            </div>
            <div v-else class="text-xs text-[--fg-4]">Not connected</div>
          </div>
        </div>

        <!-- Action buttons -->
        <div v-if="store.gcalConnected" class="flex items-center gap-2">
          <button
            data-testid="gcal-sync-now"
            :disabled="store.loading"
            @click="store.syncNow()"
            class="text-xs text-[--fg-2] hover:text-[--fg-1] disabled:opacity-50 border border-[--border-1] hover:border-[--border-2] rounded-lg px-2.5 py-1.5 transition-colors"
          >
            {{ store.loading ? '…' : 'Sync now' }}
          </button>
          <button
            data-testid="gcal-disconnect"
            :disabled="store.loading"
            @click="store.disconnectGCal()"
            class="text-sm text-[--status-block-fg] hover:opacity-80 disabled:opacity-50 border border-[--status-block-fg]/30 hover:border-[--status-block-fg]/50 rounded-lg px-3 py-1.5 transition-colors"
          >
            {{ store.loading ? '…' : 'Disconnect' }}
          </button>
        </div>
        <button
          v-else
          data-testid="gcal-connect"
          :disabled="store.loading"
          @click="store.connectGCal()"
          class="text-sm bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] font-medium rounded-lg px-3 py-1.5 transition-colors"
        >
          {{ store.loading ? '…' : 'Connect' }}
        </button>
      </div>

      <!-- Last synced caption -->
      <p
        v-if="store.gcalConnected && lastSyncedLabel"
        data-testid="gcal-last-synced"
        class="text-xs text-[--fg-4] -mt-2 mb-2"
      >
        Last synced {{ lastSyncedLabel }}
      </p>

      <!-- Info text when not connected -->
      <p v-if="!store.gcalConnected" class="text-xs text-[--fg-4]">
        Connect your Google Calendar to see events alongside your Tether tasks.
      </p>

      <!-- Error message -->
      <p v-if="store.error" class="text-xs text-[--status-block-fg] mt-2">{{ store.error }}</p>
    </div>
  </section>
</template>
