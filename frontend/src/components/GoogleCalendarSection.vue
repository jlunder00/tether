<script setup lang="ts">
import { onMounted } from 'vue'
import { useIntegrationsStore } from '../stores/integrations'

const store = useIntegrationsStore()

onMounted(() => {
  store.fetchGCalStatus()
})
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-white/50 uppercase tracking-wider mb-3">Google Calendar</h2>
    <div class="bg-gray-800 rounded-xl p-4">
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
            <div class="text-sm font-medium text-white">Google Calendar</div>
            <div v-if="store.gcalConnected" class="text-xs text-green-400 flex items-center gap-1">
              <span>✓</span>
              <span>Connected</span>
            </div>
            <div v-else class="text-xs text-white/40">Not connected</div>
          </div>
        </div>

        <!-- Action button -->
        <button
          v-if="store.gcalConnected"
          data-testid="gcal-disconnect"
          :disabled="store.loading"
          @click="store.disconnectGCal()"
          class="text-sm text-red-400 hover:text-red-300 disabled:opacity-50 border border-red-400/30 hover:border-red-300/50 rounded-lg px-3 py-1.5 transition-colors"
        >
          {{ store.loading ? '…' : 'Disconnect' }}
        </button>
        <button
          v-else
          data-testid="gcal-connect"
          :disabled="store.loading"
          @click="store.connectGCal()"
          class="text-sm bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium rounded-lg px-3 py-1.5 transition-colors"
        >
          {{ store.loading ? '…' : 'Connect' }}
        </button>
      </div>

      <!-- Info text when not connected -->
      <p v-if="!store.gcalConnected" class="text-xs text-white/40">
        Connect your Google Calendar to see events alongside your Tether tasks.
      </p>

      <!-- Error message -->
      <p v-if="store.error" class="text-xs text-red-400 mt-2">{{ store.error }}</p>
    </div>
  </section>
</template>
