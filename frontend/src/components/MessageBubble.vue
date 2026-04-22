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
    <span class="text-xs italic text-white/40">{{ msg.content }}</span>
  </div>

  <!-- User message: right-aligned bubble, plain text -->
  <div v-else-if="msg.role === 'user'" class="flex justify-end">
    <div class="max-w-[75%] rounded-2xl rounded-br-sm px-4 py-2 bg-indigo-600 text-white text-sm whitespace-pre-wrap break-words">
      {{ msg.content }}
    </div>
  </div>

  <!-- Bot message: left-aligned bubble, markdown rendered -->
  <div v-else class="flex justify-start">
    <div
      class="max-w-[75%] rounded-2xl rounded-bl-sm px-4 py-2 bg-white/10 text-white/90 text-sm prose prose-invert prose-sm break-words"
      v-html="renderedHtml"
    />
  </div>
</template>
