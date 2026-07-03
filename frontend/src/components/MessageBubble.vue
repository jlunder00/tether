<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { ChatMessage, SystemMessagePriority } from '../types/chat'

const props = defineProps<{ msg: ChatMessage }>()

const renderedHtml = computed(() => {
  if (props.msg.role !== 'bot') return ''
  const raw = marked.parse(props.msg.content) as string
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
})

// Effective priority — only meaningful on system messages; absent = 'normal'.
const systemPriority = computed<SystemMessagePriority>(() =>
  props.msg.role === 'system' ? (props.msg.priority ?? 'normal') : 'normal'
)

// Icon prefix gives color-independent scanability (a11y requirement).
const PRIORITY_ICON: Record<SystemMessagePriority, string> = {
  normal: '',
  important: '⏰',
  urgent: '🚨',
}
const priorityIcon = computed(() => PRIORITY_ICON[systemPriority.value])
</script>

<template>
  <!-- System message — plain for normal; tinted box with icon for important/urgent -->
  <div v-if="msg.role === 'system'" class="flex justify-center text-center py-1">
    <!-- Normal: plain centered italic, no visual weight -->
    <span v-if="systemPriority === 'normal'" class="text-xs italic text-[--fg-4]">
      {{ msg.content }}
    </span>
    <!-- Important / Urgent: tinted rounded box with icon prefix -->
    <span
      v-else
      :data-priority="systemPriority"
      class="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1 rounded-lg"
      :class="systemPriority === 'urgent' ? 'system-bubble-urgent' : 'system-bubble-important'"
    >
      <!-- sr-only prefix conveys priority to screen readers without visual duplication -->
      <span class="sr-only">{{ systemPriority === 'urgent' ? 'Urgent:' : 'Important:' }} </span>
      <span aria-hidden="true">{{ priorityIcon }}</span>
      {{ msg.content }}
    </span>
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
/* Priority tints for Beacon-driven system messages.
   Uses semantic status tokens defined in themes.css — works across all themes. */
.system-bubble-important {
  background-color: var(--status-important-bg);
  color: var(--status-important-fg);
  border: 1px solid var(--status-important);
}

.system-bubble-urgent {
  background-color: var(--status-urgent-bg);
  color: var(--status-urgent-fg);
  border: 1px solid var(--status-urgent);
}

/* Tailwind's `prose` hard-codes color via --tw-prose-* variables. Re-point
   them at theme tokens so bot replies stay readable in every theme/mode. */
.bot-bubble {
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
