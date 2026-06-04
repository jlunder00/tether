<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useChatStore } from '../stores/chat'
import { useAgentPickerStore } from '../stores/agentPicker'
import MessageBubble from './MessageBubble.vue'
import AgentPicker from './AgentPicker.vue'
import PermissionModal from './PermissionModal.vue'
import AgentActionPill from './AgentActionPill.vue'
import StatusIndicator from './StatusIndicator.vue'

const emit = defineEmits<{ close: [] }>()

const chatStore = useChatStore()
const agentPickerStore = useAgentPickerStore()
const draft = ref('')
const scrollEl = ref<HTMLDivElement | null>(null)
const isAtBottom = ref(true)

onMounted(() => {
  agentPickerStore.fetchPreference()
})

async function onSubmit() {
  const text = draft.value.trim()
  if (!text || chatStore.isStreaming) return
  draft.value = ''
  await chatStore.send(text)
}

function onScroll() {
  if (!scrollEl.value) return
  const el = scrollEl.value
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

watch(
  () => chatStore.messages.length,
  async () => {
    if (!isAtBottom.value) return
    await nextTick()
    scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight, behavior: 'smooth' })
  },
)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
</script>

<template>
  <div class="flex flex-col h-full" @keydown="onKeydown">
    <!-- Header -->
    <div class="flex items-center gap-2 px-4 py-3 border-b border-[--border-1] flex-shrink-0">
      <span
        class="w-2 h-2 rounded-full"
        :class="chatStore.heartbeat ? 'bg-[--status-done-fg]' : 'bg-[--status-block-fg]'"
        title="Bot status"
      />
      <span class="font-semibold text-sm text-[--fg-1]">Tether</span>
      <AgentPicker class="ml-2" />
      <button
        class="ml-auto text-[--fg-4] hover:text-[--fg-1] transition-colors p-1"
        aria-label="Close chat"
        type="button"
        @click="emit('close')"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- Message list -->
    <div
      ref="scrollEl"
      class="flex-1 overflow-y-auto p-4 space-y-3"
      @scroll="onScroll"
    >
      <MessageBubble v-for="m in chatStore.messages" :key="m.id" :msg="m" />
      <p v-if="chatStore.messages.length === 0" class="text-xs text-[--fg-5] text-center pt-8">
        Send a message to start chatting.
      </p>
      <AgentActionPill />
      <p v-if="chatStore.statusMessage" class="text-xs text-[--fg-4] text-center animate-pulse">
        {{ chatStore.statusMessage }}
      </p>
    </div>

    <!-- Composer -->
    <form
      class="border-t border-[--border-1] p-3 flex gap-2 flex-shrink-0"
      @submit.prevent="onSubmit"
    >
      <StatusIndicator />
      <textarea
        v-model="draft"
        rows="1"
        placeholder="Message Tether…"
        class="flex-1 bg-[--bg-input] text-[--fg-1] border border-[--border-input] rounded-lg px-3 py-2 text-sm outline-none resize-none focus:ring-1 focus:ring-[--accent]"
        :disabled="chatStore.isStreaming || !!chatStore.pendingPermissionRequest"
        @keydown.enter.exact.prevent="onSubmit"
      />
      <button
        v-if="chatStore.isSessionActive"
        type="button"
        aria-label="Interrupt"
        class="text-xs px-3 rounded-lg bg-[--status-block-fg]/20 text-[--status-block-fg] hover:bg-[--status-block-fg]/30 transition-colors self-end py-2"
        @click="chatStore.sendInterrupt()"
      >
        Stop
      </button>
      <button
        type="submit"
        :disabled="chatStore.isStreaming || !draft.trim() || !!chatStore.pendingPermissionRequest"
        class="text-xs px-3 rounded-lg bg-[--bg-elev-2] text-[--fg-2] hover:bg-[--bg-elev-3] disabled:opacity-30 transition-colors self-end py-2"
      >
        Send
      </button>
    </form>
    <PermissionModal />
  </div>
</template>
