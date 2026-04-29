<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { ChatMessage } from '../types/chat'

const props = defineProps<{ msg: ChatMessage }>()

const renderedHtml = computed(() => {
  if (props.msg.role !== 'bot') return ''
  const raw = marked.parse(props.msg.content) as string
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
})
</script>

<template>
  <!-- System message: centered, no bubble -->
  <div v-if="msg.role === 'system'" class="flex justify-center text-center py-1">
    <span class="text-xs italic text-[--fg-4]">{{ msg.content }}</span>
  </div>

  <!-- User message: right-aligned bubble, plain text -->
  <div v-else-if="msg.role === 'user'" class="flex justify-end">
    <div class="max-w-[75%] rounded-2xl rounded-br-sm px-4 py-2 bg-[--accent] text-[--accent-fg] text-sm whitespace-pre-wrap break-words">
      {{ msg.content }}
    </div>
  </div>

  <!-- Bot message: left-aligned bubble, markdown rendered.
       prose-invert is intentionally omitted — token-based fg colors handle
       light/dark mode, whereas prose-invert hard-codes white text and made
       bot replies unreadable in Paper / Tether-light. -->
  <div v-else class="flex justify-start">
    <div
      class="max-w-[75%] rounded-2xl rounded-bl-sm px-4 py-2 bg-[--bg-elev-2] text-[--fg-1] text-sm prose prose-sm break-words bot-bubble"
      v-html="renderedHtml"
    />
  </div>
</template>

<style scoped>
/* Tailwind's `prose` hard-codes color via --tw-prose-* variables. Re-point
   them at theme tokens so bot replies stay readable in every theme/mode. */
.bot-bubble :deep() {
  --tw-prose-body: var(--fg-1);
  --tw-prose-headings: var(--fg-1);
  --tw-prose-lead: var(--fg-2);
  --tw-prose-links: var(--accent);
  --tw-prose-bold: var(--fg-1);
  --tw-prose-counters: var(--fg-3);
  --tw-prose-bullets: var(--fg-4);
  --tw-prose-hr: var(--border-1);
  --tw-prose-quotes: var(--fg-2);
  --tw-prose-quote-borders: var(--border-2);
  --tw-prose-captions: var(--fg-3);
  --tw-prose-code: var(--fg-1);
  --tw-prose-pre-code: var(--fg-1);
  --tw-prose-pre-bg: var(--bg-elev-1);
  --tw-prose-th-borders: var(--border-2);
  --tw-prose-td-borders: var(--border-1);
}
</style>
