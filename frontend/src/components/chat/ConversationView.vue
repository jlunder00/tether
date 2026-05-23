<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { useConversationsStore } from '../../stores/conversations'
import { useConversationChat } from '../../composables/useConversationChat'
import { useAgentPickerStore } from '../../stores/agentPicker'
import { useConnectionsStore } from '../../stores/connections'
import AgentPicker from '../AgentPicker.vue'
import PriorityPill from './PriorityPill.vue'
import StateToggle from './StateToggle.vue'
import ConversationStateActions from './ConversationStateActions.vue'
import type { ConversationMessage, ConversationPriority, ConversationState } from '../../types/conversations'

const store = useConversationsStore()
const agentPickerStore = useAgentPickerStore()
const connectionsStore = useConnectionsStore()

onMounted(() => {
  agentPickerStore.fetchPreference()
  // Hydrate accepted connections for @mention autocomplete — idempotent if already loaded.
  connectionsStore.fetchConnections()
})

const draft = ref('')
const scrollEl = ref<HTMLDivElement | null>(null)
const isAtBottom = ref(true)
const editingName = ref(false)
const nameInput = ref('')
const patchingState = ref(false)

// Streaming bubble — accumulated content while streaming
const streamingBubble = ref<string | null>(null)

const selectedId = computed(() => store.selectedId)
const selected = computed(() => store.selected)
const messages = computed(() =>
  selectedId.value ? (store.messagesById.get(selectedId.value) ?? []) : []
)
const hasMore = computed(() =>
  selectedId.value ? (store.hasMoreById.get(selectedId.value) ?? false) : false
)

let chat: ReturnType<typeof useConversationChat> | null = null

watch(selectedId, (id) => {
  chat = id ? useConversationChat(id) : null
}, { immediate: true })

// ---------------------------------------------------------------------------
// @handle mention autocomplete
// ---------------------------------------------------------------------------

/** The current partially-typed handle (the text after @), or null when not in a mention. */
const activeMentionPrefix = ref<string | null>(null)

/** Index of the currently keyboard-highlighted suggestion. */
const mentionHighlight = ref(0)

/**
 * Detect whether the cursor is inside a mention context.
 * Pattern: @ not preceded by a word character, followed by optional word chars.
 * This prevents email addresses (name@domain) from triggering autocomplete.
 */
function detectMention(text: string): string | null {
  const match = text.match(/(?:^|[^\w])@(\w*)$/)
  return match ? match[1] : null
}

/** Up to 8 accepted connections matching the current prefix. */
const mentionSuggestions = computed(() => {
  const prefix = activeMentionPrefix.value
  if (prefix === null) return []
  const lower = prefix.toLowerCase()
  return connectionsStore.accepted
    .filter(c => c.other_username.toLowerCase().startsWith(lower))
    .slice(0, 8)
})

function onInput(e: Event) {
  const el = e.target as HTMLTextAreaElement
  const textUpToCursor = el.value.slice(0, el.selectionStart ?? el.value.length)
  activeMentionPrefix.value = detectMention(textUpToCursor)
  mentionHighlight.value = 0
}

function insertMention(username: string) {
  // Replace the partial @prefix with the full @username + trailing space.
  const prefix = activeMentionPrefix.value ?? ''
  const pattern = new RegExp(`(^|[^\\w])@${escapeRegex(prefix)}$`)
  draft.value = draft.value.replace(pattern, (_, pre) => `${pre}@${username} `)
  activeMentionPrefix.value = null
  mentionHighlight.value = 0
}

function closeMention() {
  activeMentionPrefix.value = null
  mentionHighlight.value = 0
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

// ---------------------------------------------------------------------------
// Scroll helpers
// ---------------------------------------------------------------------------

function onScroll() {
  if (!scrollEl.value) return
  const el = scrollEl.value
  isAtBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

async function scrollToBottom() {
  if (!isAtBottom.value) return
  await nextTick()
  scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight, behavior: 'smooth' })
}

watch(() => messages.value.length, scrollToBottom)

// ---------------------------------------------------------------------------
// Send
// ---------------------------------------------------------------------------

async function onSend() {
  if (!draft.value.trim() || !selectedId.value || !chat) return
  const text = draft.value.trim()
  draft.value = ''
  closeMention()
  isAtBottom.value = true

  // Append user message locally
  const userMsg: ConversationMessage = {
    id: `local-${Date.now()}`,
    role: 'user',
    body: text,
    source: 'chat',
    channel: 'web',
    created_at: new Date().toISOString(),
  }
  store.appendMessage(selectedId.value, userMsg)

  streamingBubble.value = ''
  const convId = selectedId.value

  await chat.send(text, (chunk: string) => {
    if (streamingBubble.value !== null) {
      streamingBubble.value += chunk
    }
    scrollToBottom()
  })

  // Finalize streaming bubble as assistant message
  if (streamingBubble.value) {
    const assistantMsg: ConversationMessage = {
      id: `local-assistant-${Date.now()}`,
      role: 'assistant',
      body: streamingBubble.value,
      source: 'chat',
      channel: 'web',
      created_at: new Date().toISOString(),
    }
    store.appendMessage(convId, assistantMsg)
  }
  streamingBubble.value = null
  await scrollToBottom()
}

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

function onKeydown(e: KeyboardEvent) {
  // Handle autocomplete navigation first
  if (mentionSuggestions.value.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      mentionHighlight.value = (mentionHighlight.value + 1) % mentionSuggestions.value.length
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      mentionHighlight.value = (mentionHighlight.value - 1 + mentionSuggestions.value.length) % mentionSuggestions.value.length
      return
    }
    if (e.key === 'Tab' || (e.key === 'Enter' && mentionSuggestions.value.length > 0)) {
      e.preventDefault()
      const suggestion = mentionSuggestions.value[mentionHighlight.value]
      if (suggestion) insertMention(suggestion.other_username)
      return
    }
    if (e.key === 'Escape') {
      closeMention()
      return
    }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSend()
  }
}

// ---------------------------------------------------------------------------
// Inline name editing
// ---------------------------------------------------------------------------

function startEditName() {
  if (!selected.value) return
  nameInput.value = selected.value.name
  editingName.value = true
  nextTick(() => {
    const el = document.querySelector<HTMLInputElement>('[data-name-input]')
    el?.focus()
  })
}

async function commitNameEdit() {
  if (!selectedId.value || !editingName.value) return
  editingName.value = false
  const trimmed = nameInput.value.trim()
  if (trimmed && trimmed !== selected.value?.name) {
    await store.patch(selectedId.value, { name: trimmed })
  }
}

async function onPriorityChange(p: ConversationPriority) {
  if (!selectedId.value) return
  await store.patch(selectedId.value, { priority: p })
}

async function onStateChange(s: ConversationState) {
  if (!selectedId.value || patchingState.value) return
  patchingState.value = true
  try {
    await store.patch(selectedId.value, { state: s })
  } finally {
    patchingState.value = false
  }
}

// ---------------------------------------------------------------------------
// Pending / rejected state actions (D1)
// ---------------------------------------------------------------------------

async function onApprove(convId: string) {
  if (patchingState.value) return
  patchingState.value = true
  try {
    await store.patch(convId, { state: 'open' })
  } finally {
    patchingState.value = false
  }
}

async function onDismiss(convId: string) {
  if (patchingState.value) return
  patchingState.value = true
  try {
    await store.discard(convId)
  } finally {
    patchingState.value = false
  }
}

async function onRestore(convId: string) {
  if (patchingState.value) return
  patchingState.value = true
  try {
    await store.patch(convId, { state: 'open' })
  } finally {
    patchingState.value = false
  }
}

async function loadOlder() {
  if (!selectedId.value || !scrollEl.value) return
  const firstMsgId = messages.value[0]?.id
  await store.loadMessagesOlder(selectedId.value)
  // Restore scroll position: find the element that was first visible
  if (firstMsgId) {
    await nextTick()
    const el = scrollEl.value?.querySelector(`[data-msg-id="${firstMsgId}"]`) as HTMLElement | null
    el?.scrollIntoView({ block: 'start' })
  }
}

const isStreaming = computed(() => chat?.isStreaming.value ?? false)

// ---------------------------------------------------------------------------
// @handle rendering in messages
// ---------------------------------------------------------------------------

/** Replace @handle tokens in message body with accent-coloured spans. */
function renderBody(body: string): string {
  return body.replace(
    /(^|[^\w])(@\w+)/g,
    (_, pre, handle) =>
      `${pre}<span class="text-[--accent] font-medium">${handle}</span>`,
  )
}
</script>

<template>
  <div class="flex flex-col h-full bg-[--bg-1]">
    <!-- Empty state -->
    <div v-if="!selected" class="flex-1 flex items-center justify-center">
      <p class="text-sm text-[--fg-5]">Select a conversation or create one</p>
    </div>

    <template v-else>
      <!-- Header -->
      <div class="flex items-center gap-2 px-4 py-3 border-b border-[--border-1] flex-shrink-0">
        <!-- Inline-editable name -->
        <div class="flex-1 min-w-0">
          <input
            v-if="editingName"
            v-model="nameInput"
            data-name-input
            type="text"
            class="w-full px-1 py-0.5 text-sm font-semibold bg-transparent border-b border-blue-500 text-[--fg-1] focus:outline-none"
            @blur="commitNameEdit"
            @keydown.enter.prevent="commitNameEdit"
            @keydown.escape="editingName = false"
          />
          <span
            v-else
            data-testid="conv-name"
            class="text-sm font-semibold text-[--fg-1] cursor-pointer hover:underline truncate block"
            @click="startEditName"
          >
            {{ selected.name }}
          </span>
        </div>

        <PriorityPill
          :priority="selected.priority"
          :clickable="true"
          @change="onPriorityChange"
        />

        <span v-if="selected.folder_name" class="text-xs text-[--fg-4] truncate max-w-24">
          {{ selected.folder_name }}
        </span>

        <!-- Open/closed toggle — only shown for open & closed states.
             Pending/rejected use ConversationStateActions instead. -->
        <StateToggle
          v-if="selected.state === 'open' || selected.state === 'closed'"
          :state="selected.state"
          :loading="patchingState"
          @change="onStateChange"
        />

        <!-- Pending / rejected actions + open overflow (D1) -->
        <ConversationStateActions
          :conv-id="selected.id"
          :state="selected.state"
          :loading="patchingState"
          @approve="onApprove"
          @dismiss="onDismiss"
          @restore="onRestore"
        />
      </div>

      <!-- Messages area -->
      <div
        ref="scrollEl"
        class="flex-1 overflow-y-auto p-4 space-y-3"
        @scroll="onScroll"
      >
        <!-- Load older button -->
        <div v-if="hasMore" class="flex justify-center">
          <button
            type="button"
            class="text-xs text-[--fg-4] hover:text-[--fg-2] px-3 py-1 rounded border border-[--border-1] hover:bg-[--bg-2]"
            @click="loadOlder"
          >
            Load older messages
          </button>
        </div>

        <!-- Message list -->
        <div
          v-for="msg in messages"
          :key="msg.id"
          :data-msg-id="msg.id"
          class="flex"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[75%] rounded-lg px-3 py-2 text-sm"
            :class="msg.role === 'user'
              ? 'bg-blue-500 text-white rounded-br-none'
              : 'bg-[--bg-2] text-[--fg-1] rounded-bl-none'"
          >
            <!-- Render @handles with accent colour; sanitised by v-html (no user HTML allowed) -->
            <!-- eslint-disable-next-line vue/no-v-html -->
            <span v-html="renderBody(msg.body)" />
          </div>
        </div>

        <!-- Streaming bubble -->
        <div v-if="streamingBubble !== null" class="flex justify-start">
          <div class="max-w-[75%] rounded-lg px-3 py-2 text-sm bg-[--bg-2] text-[--fg-1] rounded-bl-none opacity-80">
            {{ streamingBubble || '…' }}
          </div>
        </div>
      </div>

      <!-- Composer -->
      <div class="flex-shrink-0 border-t border-[--border-1] px-4 py-3">
        <div class="flex items-center gap-2 mb-2">
          <AgentPicker />
        </div>

        <!-- Textarea + mention dropdown wrapper -->
        <div class="relative flex gap-2">
          <div class="flex-1 relative">
            <textarea
              v-model="draft"
              rows="2"
              class="w-full resize-none rounded border border-[--border-1] bg-[--bg-2] text-[--fg-1] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Type a message… (Enter to send, Shift+Enter for newline)"
              :disabled="isStreaming"
              @input="onInput"
              @keydown="onKeydown"
            />

            <!-- @mention autocomplete dropdown -->
            <ul
              v-if="mentionSuggestions.length > 0"
              data-mention-dropdown
              class="absolute bottom-full left-0 mb-1 w-48 max-h-48 overflow-y-auto bg-[--bg-elev-2] border border-[--border-1] rounded-lg shadow-lg z-50 py-1"
            >
              <li
                v-for="(suggestion, idx) in mentionSuggestions"
                :key="suggestion.other_user_id"
                data-mention-item
                class="px-3 py-1.5 text-sm cursor-pointer transition-colors"
                :class="idx === mentionHighlight
                  ? 'bg-[--accent] text-[--accent-fg]'
                  : 'text-[--fg-1] hover:bg-[--bg-elev-3]'"
                @click="insertMention(suggestion.other_username)"
              >
                {{ suggestion.other_username }}
              </li>
            </ul>
          </div>

          <div class="flex flex-col gap-1">
            <button
              type="submit"
              class="px-3 py-2 rounded bg-blue-500 text-white text-sm hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
              :disabled="!draft.trim() || isStreaming"
              @click="onSend"
            >
              Send
            </button>
            <button
              v-if="isStreaming"
              type="button"
              class="px-3 py-2 rounded bg-[--status-block-fg] text-white text-sm hover:opacity-80"
              @click="chat?.interrupt()"
            >
              Stop
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
