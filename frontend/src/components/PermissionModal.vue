<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'

const TIMEOUT_MS = 60_000

const chatStore = useChatStore()
const showDetails = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function clearTimer() {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function startTimer() {
  clearTimer()
  timer = setTimeout(() => {
    if (chatStore.pendingPermissionRequest) {
      chatStore.respondToPermission(chatStore.pendingPermissionRequest.request_id, false)
    }
  }, TIMEOUT_MS)
}

watch(
  () => chatStore.pendingPermissionRequest,
  (req) => {
    showDetails.value = false
    if (req) startTimer()
    else clearTimer()
  },
  { immediate: true },
)

onUnmounted(() => clearTimer())

function approve() {
  clearTimer()
  if (chatStore.pendingPermissionRequest) {
    chatStore.respondToPermission(chatStore.pendingPermissionRequest.request_id, true)
  }
}

function deny() {
  clearTimer()
  if (chatStore.pendingPermissionRequest) {
    chatStore.respondToPermission(chatStore.pendingPermissionRequest.request_id, false)
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="chatStore.pendingPermissionRequest"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
    >
      <div class="bg-[--bg-elev-1] border border-[--border-1] rounded-xl shadow-xl p-6 max-w-sm w-full mx-4">
        <h2 class="text-sm font-semibold text-[--fg-1] mb-2">Permission Request</h2>
        <p class="text-sm text-[--fg-2] mb-4">{{ chatStore.pendingPermissionRequest.summary }}</p>

        <button
          v-if="chatStore.pendingPermissionRequest.details.length"
          type="button"
          class="text-xs text-[--fg-4] hover:text-[--fg-2] mb-3 transition-colors block"
          @click="showDetails = !showDetails"
        >
          {{ showDetails ? 'Hide details' : 'Show more details' }}
        </button>

        <div v-if="showDetails" class="mb-4 space-y-1">
          <div
            v-for="d in chatStore.pendingPermissionRequest.details"
            :key="d.label"
            class="text-xs text-[--fg-3]"
          >
            <span class="font-medium text-[--fg-2]">{{ d.label }}:</span> {{ d.value }}
          </div>
        </div>

        <div class="flex gap-2 justify-end">
          <button
            type="button"
            class="px-4 py-1.5 text-xs rounded-lg bg-[--bg-elev-2] text-[--fg-2] hover:bg-[--bg-elev-3] transition-colors"
            @click="deny"
          >
            Deny
          </button>
          <button
            type="button"
            class="px-4 py-1.5 text-xs rounded-lg bg-[--accent] text-[--accent-fg] hover:opacity-90 transition-opacity"
            @click="approve"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
