<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useConversationsStore } from '../../stores/conversations'
import { useContextStore } from '../../stores/context'
import type { ConversationDetail } from '../../types/conversations'

const props = defineProps<{ nodeId: string | null }>()
const emit  = defineEmits<{ 'open-conversation': [id: string] }>()

const convStore = useConversationsStore()
const ctxStore  = useContextStore()

const newChatText = ref('')

// Conversations scoped to the active node
const conversations = computed(() =>
  props.nodeId
    ? convStore.list.filter(c => c.context_node_id === props.nodeId)
    : convStore.list
)

// Breadcrumb path for the active node
const pathSegs = computed(() => {
  if (!props.nodeId) return []
  const segs: string[] = []
  let id: string | null = props.nodeId
  while (id) {
    const node = ctxStore.nodes[id]
    if (!node) break
    segs.unshift(node.name)
    id = node.parent_id ?? null
  }
  return segs
})

const activeNode = computed(() =>
  props.nodeId ? ctxStore.nodes[props.nodeId] ?? null : null
)

watch(() => props.nodeId, (id) => {
  convStore.refresh(id ? { context_node_id: id } : undefined)
}, { immediate: true })

async function startChat() {
  if (!newChatText.value.trim()) return
  const conv = await convStore.create({
    name: newChatText.value.trim(),
    context_node_id: props.nodeId ?? undefined,
  })
  if (conv) {
    newChatText.value = ''
    emit('open-conversation', conv.id)
  }
}

function onDragStart(conv: ConversationDetail, evt: DragEvent) {
  evt.dataTransfer?.setData('text/plain', JSON.stringify({ conversationId: conv.id }))
}

function formatTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const days = Math.floor(diff / 86400000)
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7)  return `${days}d ago`
  return new Date(iso).toLocaleDateString('en', { month: 'short', day: 'numeric' })
}
</script>

<template>
  <div class="folder-center">

    <!-- ── New-chat composer ── -->
    <div class="newchat">
      <!-- Breadcrumb -->
      <div class="newchat__crumb">
        <template v-for="(seg, i) in pathSegs" :key="i">
          <span class="newchat__crumb-seg">{{ seg }}</span>
          <span v-if="i < pathSegs.length - 1" class="newchat__crumb-sep">›</span>
        </template>
      </div>

      <textarea
        v-model="newChatText"
        class="newchat__area"
        :placeholder="`Ask Tether anything about ${activeNode?.name ?? 'this folder'}…`"
        rows="3"
        @keydown.enter.meta.exact="startChat"
        @keydown.enter.ctrl.exact="startChat"
      />

      <div class="newchat__footer">
        <div class="newchat__ctx">
          <span class="newchat__ctx-dot" />
          context: {{ pathSegs.join(' · ') || 'all' }}
        </div>
        <button
          data-testid="start-chat-btn"
          class="newchat__btn"
          :disabled="!newChatText.trim()"
          @click="startChat"
        >
          Start chat →
        </button>
      </div>
    </div>

    <!-- ── Conversation list ── -->
    <div class="convlist">
      <div class="convlist__hdr">
        Conversations
        <span class="convlist__count">{{ conversations.length }}</span>
      </div>

      <!-- Empty state -->
      <div v-if="conversations.length === 0" class="convlist__empty">
        <div class="convlist__empty-icon">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
               stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 3a1 1 0 011-1h10a1 1 0 011 1v7a1 1 0 01-1 1H9l-3 2v-2H3a1 1 0 01-1-1V3z"/>
          </svg>
        </div>
        <div class="convlist__empty-title">No conversations yet</div>
        <div class="convlist__empty-sub">
          Start a chat above to discuss {{ activeNode?.name ?? 'this folder' }} with Tether.
        </div>
      </div>

      <!-- Conversation cards -->
      <div
        v-for="conv in conversations"
        :key="conv.id"
        :data-testid="`conv-row-${conv.id}`"
        class="convitem"
        draggable="true"
        @click="emit('open-conversation', conv.id)"
        @dragstart="onDragStart(conv, $event)"
      >
        <span class="convitem__dot" :class="{ 'convitem__dot--on': conv.priority === 'urgent' || conv.priority === 'high' }" />
        <div class="convitem__body">
          <div class="convitem__title">{{ conv.name }}</div>
          <div class="convitem__meta">
            <span class="convitem__ts">{{ formatTime(conv.last_message_at) }}</span>
            <span class="convitem__path">{{ pathSegs.join(' › ') }}</span>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.folder-center {
  flex: 1; min-width: 0;
  display: flex; flex-direction: column;
  overflow: hidden; background: var(--bg-canvas);
}

/* ── Composer ── */
.newchat {
  flex-shrink: 0;
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--border-1);
}
.newchat__crumb {
  display: flex; align-items: center; gap: 5px;
  font-family: var(--font-mono); font-size: 10.5px;
  color: var(--fg-5); margin-bottom: 10px;
}
.newchat__crumb-seg { cursor: pointer; transition: color 150ms; }
.newchat__crumb-seg:hover { color: var(--fg-2); }
.newchat__crumb-sep { color: var(--fg-6); }
.newchat__area {
  display: block; width: 100%;
  background: var(--bg-elev-1);
  border: 1px solid var(--border-1); border-radius: var(--radius-sharp);
  color: var(--fg-2); font-family: var(--font-sans); font-size: 13.5px; line-height: 1.6;
  padding: 12px 14px; resize: none; outline: none; box-sizing: border-box;
  transition: border-color 150ms, background 150ms;
}
.newchat__area::placeholder { color: var(--fg-5); }
.newchat__area:focus { border-color: var(--accent-soft); background: var(--bg-elev-2); }
.newchat__footer {
  display: flex; align-items: center; gap: 10px; margin-top: 10px;
}
.newchat__ctx {
  display: flex; align-items: center; gap: 6px;
  font-family: var(--font-mono); font-size: 11px; color: var(--fg-5);
}
.newchat__ctx-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0;
}
.newchat__btn {
  margin-left: auto;
  padding: 6px 16px; font-size: 12.5px;
  background: var(--accent); color: var(--accent-fg);
  border: none; border-radius: var(--radius-sharp); cursor: pointer;
  font-family: var(--font-sans); transition: opacity 150ms;
}
.newchat__btn:hover:not(:disabled) { opacity: 0.88; }
.newchat__btn:disabled { opacity: 0.4; cursor: default; }

/* ── List ── */
.convlist { flex: 1; overflow-y: auto; }
.convlist__hdr {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 24px 8px;
  font-family: var(--font-mono); font-size: 9.5px;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--fg-5);
  border-bottom: 1px solid var(--border-soft);
  position: sticky; top: 0; z-index: 1; background: var(--bg-canvas);
}
.convlist__count {
  background: var(--bg-elev-3); color: var(--fg-5);
  font-size: 9px; padding: 1px 5px; border-radius: 9999px;
}
.convlist__empty {
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 48px 32px; gap: 12px; text-align: center;
}
.convlist__empty-icon {
  width: 34px; height: 34px;
  border: 1px solid var(--border-1); border-radius: var(--radius-soft);
  display: flex; align-items: center; justify-content: center; color: var(--fg-6);
}
.convlist__empty-title {
  font-size: 13.5px; font-weight: 600;
  color: var(--fg-3); font-family: var(--font-display);
}
.convlist__empty-sub {
  font-size: 12.5px; color: var(--fg-5); line-height: 1.6; max-width: 280px;
}
.convitem {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 13px 24px; border-bottom: 1px solid var(--border-soft);
  cursor: pointer; transition: background 150ms;
}
.convitem:hover { background: var(--bg-elev-1); }
.convitem__dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0;
  margin-top: 5px; visibility: hidden;
}
.convitem__dot--on { visibility: visible; }
.convitem__body { flex: 1; min-width: 0; }
.convitem__title {
  font-size: 13.5px; font-weight: 500; color: var(--fg-1); margin-bottom: 4px;
}
.convitem__meta {
  display: flex; align-items: center; gap: 10px;
  font-family: var(--font-mono); font-size: 10.5px; color: var(--fg-5);
}
.convitem__path { color: var(--fg-6); }
</style>
