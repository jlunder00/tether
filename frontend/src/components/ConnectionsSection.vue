<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConnectionsStore } from '../stores/connections'

const store = useConnectionsStore()
const requestUsername = ref('')

onMounted(() => {
  store.fetchConnections()
})

function dismissError() {
  store.error = null
}

async function handleSendRequest() {
  const username = requestUsername.value.trim()
  if (!username) return
  await store.sendRequest(username)
  if (!store.error) requestUsername.value = ''
}

function truncateUuid(uuid: string): string {
  return uuid.length > 8 ? `${uuid.slice(0, 8)}…` : uuid
}
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Connections</h2>

    <!-- Spinner -->
    <div v-if="store.loading && store.connections.length === 0" class="bg-[--bg-elev-1] rounded-xl p-4">
      <p class="text-sm text-[--fg-4]">Loading…</p>
    </div>

    <!-- Error alert -->
    <div
      v-if="store.error"
      class="bg-[--status-block-bg] border border-[--status-block-fg]/30 rounded-xl p-3 mb-3 flex items-start justify-between gap-2"
      data-testid="connections-error"
    >
      <p class="text-sm text-[--status-block-fg]">{{ store.error }}</p>
      <button @click="dismissError" class="text-[--status-block-fg]/60 hover:text-[--status-block-fg] text-lg leading-none flex-shrink-0">×</button>
    </div>

    <!-- Pending incoming requests -->
    <div class="bg-[--bg-elev-1] rounded-xl p-4 mb-3">
      <h3 class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-3">Pending Requests</h3>
      <div v-if="store.pending_incoming.length === 0" class="text-sm text-[--fg-5]">
        No pending requests
      </div>
      <ul v-else class="space-y-2">
        <li
          v-for="conn in store.pending_incoming"
          :key="conn.id"
          class="flex items-center justify-between gap-2"
          :data-testid="`incoming-${conn.id}`"
        >
          <span class="text-sm text-[--fg-1] font-mono" :title="conn.other_user_id">
            {{ truncateUuid(conn.other_user_id) }}
          </span>
          <div class="flex gap-1.5">
            <button
              :disabled="store.loading"
              @click="store.acceptConnection(conn.id)"
              class="text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg px-2.5 py-1 transition-colors"
              :data-testid="`accept-${conn.id}`"
            >
              Accept
            </button>
            <button
              :disabled="store.loading"
              @click="store.declineConnection(conn.id, false)"
              class="text-xs text-[--fg-3] hover:text-[--fg-1] disabled:opacity-50 border border-[--border-1] hover:border-[--border-2] rounded-lg px-2.5 py-1 transition-colors"
              :data-testid="`decline-${conn.id}`"
            >
              Decline
            </button>
            <button
              :disabled="store.loading"
              @click="store.declineConnection(conn.id, true)"
              class="text-xs text-[--status-block-fg] hover:opacity-80 disabled:opacity-50 border border-[--status-block-fg]/30 hover:border-[--status-block-fg]/50 rounded-lg px-2.5 py-1 transition-colors"
              :data-testid="`block-${conn.id}`"
            >
              Block
            </button>
          </div>
        </li>
      </ul>
    </div>

    <!-- Accepted connections -->
    <div class="bg-[--bg-elev-1] rounded-xl p-4 mb-3">
      <h3 class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-3">Your Connections</h3>
      <div v-if="store.accepted.length === 0" class="text-sm text-[--fg-5]">
        No connections yet
      </div>
      <ul v-else class="space-y-3">
        <li
          v-for="conn in store.accepted"
          :key="conn.id"
          class="flex items-center justify-between gap-2"
          :data-testid="`accepted-${conn.id}`"
        >
          <div class="flex items-center gap-2">
            <span class="text-sm text-[--fg-1] font-mono" :title="conn.other_user_id">
              {{ truncateUuid(conn.other_user_id) }}
            </span>
            <span class="text-[10px] bg-[--status-done-bg] text-[--status-done-fg] rounded px-1.5 py-0.5 font-medium tracking-wide">
              connected
            </span>
          </div>
          <!-- Auto-schedule toggle -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-[--fg-4]">Auto-schedule</span>
            <button
              :disabled="store.loading"
              @click="store.toggleAutoSchedule(conn.id, !conn.auto_schedule)"
              :class="conn.auto_schedule ? 'bg-indigo-600' : 'bg-[--bg-elev-3]'"
              class="relative w-9 h-5 rounded-full transition-colors disabled:opacity-50"
              :data-testid="`auto-schedule-${conn.id}`"
              :aria-pressed="conn.auto_schedule"
              :aria-label="`Auto-schedule for ${conn.other_user_id}`"
            >
              <span
                :class="conn.auto_schedule ? 'translate-x-4' : 'translate-x-0.5'"
                class="inline-block w-4 h-4 bg-white rounded-full transition-transform transform mt-0.5"
              />
            </button>
          </div>
        </li>
      </ul>
    </div>

    <!-- Send request + pending outgoing -->
    <div class="bg-[--bg-elev-1] rounded-xl p-4">
      <h3 class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-3">Add Connection</h3>
      <div class="flex gap-2 mb-3">
        <input
          v-model="requestUsername"
          type="text"
          placeholder="Username"
          class="flex-1 bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 placeholder:text-[--fg-5]"
          @keydown.enter="handleSendRequest"
          data-testid="request-username-input"
        />
        <button
          :disabled="store.loading || !requestUsername.trim()"
          @click="handleSendRequest"
          class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors"
          data-testid="send-request-btn"
        >
          {{ store.loading ? '…' : 'Send request' }}
        </button>
      </div>

      <!-- Pending outgoing (cancel not yet supported by backend) -->
      <div v-if="store.pending_outgoing.length > 0">
        <p class="text-xs text-[--fg-5] mb-2">Sent — waiting for response</p>
        <ul class="space-y-1.5">
          <li
            v-for="conn in store.pending_outgoing"
            :key="conn.id"
            class="flex items-center gap-2"
            :data-testid="`outgoing-${conn.id}`"
          >
            <span class="text-sm text-[--fg-3] font-mono" :title="conn.other_user_id">
              {{ truncateUuid(conn.other_user_id) }}
            </span>
            <span class="text-[10px] text-[--fg-6]">pending</span>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
