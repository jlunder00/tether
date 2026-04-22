<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useChatStore } from '../stores/chat'
import MessageBubble from './MessageBubble.vue'

const emit = defineEmits<{ close: [] }>()

const chatStore = useChatStore()
const draft = ref('')
const scrollEl = ref<HTMLDivElement | null>(null)
const isAtBottom = ref(true)

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
    <div class="flex items-center gap-2 px-4 py-3 border-b border-white/10 flex-shrink-0">
      <span
        class="w-2 h-2 rounded-full"
        :class="chatStore.heartbeat ? 'bg-green-400' : 'bg-red-400'"
        title="Bot status"
      />
      <span class="font-semibold text-sm">Tether</span>
      <button
        class="ml-auto text-white/40 hover:text-white/80 transition-colors p-1"
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
      <p v-if="chatStore.messages.length === 0" class="text-xs text-white/30 text-center pt-8">
        Send a message to start chatting.
      </p>
    </div>

    <!-- Composer -->
    <form
      class="border-t border-white/10 p-3 flex gap-2 flex-shrink-0"
      @submit.prevent="onSubmit"
    >
      <textarea
        v-model="draft"
        rows="1"
        placeholder="Message Tether…"
        class="flex-1 bg-white/5 rounded-lg px-3 py-2 text-sm outline-none resize-none focus:ring-1 focus:ring-indigo-500"
        @keydown.enter.exact.prevent="onSubmit"
      />
      <button
        type="submit"
        :disabled="chatStore.isStreaming || !draft.trim()"
        class="text-xs px-3 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-30 transition-colors self-end py-2"
      >
        Send
      </button>
    </form>
  </div>
</template>
