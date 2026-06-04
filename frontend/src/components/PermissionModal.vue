<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'
import type { PermissionKind } from '../types/chat'

const TIMEOUT_MS = 60_000

const KIND_LABELS: Record<PermissionKind, string> = {
  read_out_of_scope: 'Read out-of-scope content',
  user_section_edit: 'Edit your section',
  destructive: 'Destructive action',
}

const chatStore = useChatStore()
const showReason = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

const kindLabel = computed(() => {
  const req = chatStore.pendingPermissionRequest
  return req ? KIND_LABELS[req.kind] : ''
})

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
    showReason.value = false
    if (req) startTimer()
    else clearTimer()
  },
  { immediate: true },
)

onUnmounted(() => clearTimer())

function respond(approve: boolean) {
  clearTimer()
  const req = chatStore.pendingPermissionRequest
  if (req) chatStore.respondToPermission(req.request_id, approve)
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
        <p class="text-sm text-[--fg-2] mb-1">
          <span class="font-medium">{{ kindLabel }}</span>
        </p>
        <p class="text-xs text-[--fg-3] font-mono mb-4 break-all">{{ chatStore.pendingPermissionRequest.target }}</p>

        <button
          v-if="chatStore.pendingPermissionRequest.reason_from_bot"
          type="button"
          class="text-xs text-[--fg-4] hover:text-[--fg-2] mb-3 transition-colors block"
          @click="showReason = !showReason"
        >
          {{ showReason ? 'Hide reason' : 'Show reason' }}
        </button>

        <div v-if="showReason && chatStore.pendingPermissionRequest.reason_from_bot" class="mb-4">
          <p class="text-xs text-[--fg-3]">{{ chatStore.pendingPermissionRequest.reason_from_bot }}</p>
        </div>

        <div class="flex gap-2 justify-end">
          <button
            type="button"
            class="px-4 py-1.5 text-xs rounded-lg bg-[--bg-elev-2] text-[--fg-2] hover:bg-[--bg-elev-3] transition-colors"
            @click="respond(false)"
          >
            Deny
          </button>
          <button
            type="button"
            class="px-4 py-1.5 text-xs rounded-lg bg-[--accent] text-[--accent-fg] hover:opacity-90 transition-opacity"
            @click="respond(true)"
          >
            Approve
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
