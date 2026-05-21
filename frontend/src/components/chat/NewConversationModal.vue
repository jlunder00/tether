<script setup lang="ts">
import { ref } from 'vue'
import { useConversationsStore } from '../../stores/conversations'
import type { ConversationDetail } from '../../types/conversations'

defineProps<{
  open: boolean
  contextNodes: { id: string; name: string }[]
}>()

const emit = defineEmits<{
  close: []
  created: [conv: ConversationDetail]
}>()

const conversationsStore = useConversationsStore()

const name = ref('')
const type = ref<'interactive' | 'passive'>('interactive')
const priority = ref<'low' | 'normal' | 'high' | 'urgent'>('normal')
const contextNodeId = ref<string>('')
const submitting = ref(false)

async function onSubmit() {
  if (!name.value.trim() || submitting.value) return
  submitting.value = true
  try {
    const result = await conversationsStore.create({
      name: name.value.trim(),
      type: type.value,
      priority: priority.value,
      context_node_id: contextNodeId.value || undefined,
    })
    if (result) {
      emit('created', result)
      emit('close')
      name.value = ''
      type.value = 'interactive'
      priority.value = 'normal'
      contextNodeId.value = ''
    }
  } finally {
    submitting.value = false
  }
}

function onBackdropClick(e: MouseEvent) {
  if (e.target === e.currentTarget) emit('close')
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
    @click="onBackdropClick"
  >
    <div class="bg-[--bg-1] border border-[--border-1] rounded-lg shadow-xl w-full max-w-md p-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-[--fg-1]">New Conversation</h2>
        <button
          type="button"
          aria-label="Close modal"
          class="text-[--fg-4] hover:text-[--fg-1] transition-colors"
          @click="emit('close')"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <form @submit.prevent="onSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-[--fg-2] mb-1">Name *</label>
          <input
            v-model="name"
            type="text"
            class="w-full px-3 py-2 rounded border border-[--border-1] bg-[--bg-2] text-[--fg-1] focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Conversation name"
            required
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-[--fg-2] mb-1">Type</label>
          <select
            v-model="type"
            class="w-full px-3 py-2 rounded border border-[--border-1] bg-[--bg-2] text-[--fg-1] focus:outline-none"
          >
            <option value="interactive">Interactive</option>
            <option value="passive">Passive</option>
          </select>
        </div>

        <div>
          <label class="block text-sm font-medium text-[--fg-2] mb-1">Priority</label>
          <select
            v-model="priority"
            class="w-full px-3 py-2 rounded border border-[--border-1] bg-[--bg-2] text-[--fg-1] focus:outline-none"
          >
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>

        <div v-if="contextNodes.length > 0">
          <label class="block text-sm font-medium text-[--fg-2] mb-1">Context (optional)</label>
          <select
            v-model="contextNodeId"
            class="w-full px-3 py-2 rounded border border-[--border-1] bg-[--bg-2] text-[--fg-1] focus:outline-none"
          >
            <option value="">None</option>
            <option v-for="node in contextNodes" :key="node.id" :value="node.id">
              {{ node.name }}
            </option>
          </select>
        </div>

        <div class="flex justify-end gap-2 pt-2">
          <button
            type="button"
            class="px-4 py-2 text-sm rounded border border-[--border-1] text-[--fg-2] hover:bg-[--bg-2]"
            @click="emit('close')"
          >
            Cancel
          </button>
          <button
            type="submit"
            class="px-4 py-2 text-sm rounded bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="!name.trim() || submitting"
          >
            {{ submitting ? 'Creating…' : 'Create' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
