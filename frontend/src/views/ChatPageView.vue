<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConversationsStore } from '../stores/conversations'
import { useContextStore } from '../stores/context'
import ContextNodeSidebar from '../components/chat/ContextNodeSidebar.vue'
import FolderCenterPanel  from '../components/chat/FolderCenterPanel.vue'
import ConversationView   from '../components/chat/ConversationView.vue'
import ProjectDetailsPanel from '../components/chat/ProjectDetailsPanel.vue'

// ─── Collapse state ───────────────────────────────────────
const leftOpen  = ref(true)
const rightOpen = ref(true)

// ─── Selection state ──────────────────────────────────────
// activeNodeId: the focused folder node
// convStore.selectedId: the active conversation (null = no conv open)
const activeNodeId = ref<string | null>(null)
const convStore    = useConversationsStore()
const ctxStore     = useContextStore()

const mode = computed<'folder' | 'conversation'>(() =>
  convStore.selectedId !== null ? 'conversation' : 'folder'
)

// ─── Deep-link hydration ──────────────────────────────────
const route  = useRoute()
const router = useRouter()

onMounted(async () => {
  await ctxStore.fetchRootNodes()

  if (route.name === 'chat-node' && route.params.nodeId) {
    activeNodeId.value = route.params.nodeId as string
  } else if (route.name === 'chat-conversation' && route.params.convId) {
    convStore.select(route.params.convId as string)
    // also set activeNodeId from the conversation's context_node_id
    await convStore.refresh()
    const conv = convStore.list.find(c => c.id === route.params.convId)
    if (conv?.context_node_id) activeNodeId.value = conv.context_node_id
  }
})

// ─── Navigation helpers ───────────────────────────────────
function onSelectNode(nodeId: string | null) {
  activeNodeId.value = nodeId
  convStore.select(null)              // deselect any open conversation
  router.replace(nodeId
    ? { name: 'chat-node', params: { nodeId } }
    : { name: 'chat' })
}

function onSelectConversation(convId: string) {
  convStore.select(convId)
  router.replace({ name: 'chat-conversation', params: { convId } })
}
</script>

<template>
  <div class="flex h-screen overflow-hidden" style="background:var(--bg-canvas)">

    <!-- ── Col 1: folder tree ── -->
    <template v-if="leftOpen">
      <ContextNodeSidebar
        :active-node-id="activeNodeId"
        @update:active-node-id="onSelectNode"
        @collapse="leftOpen = false"
      />
    </template>
    <div v-else class="k1-col-strip k1-col-strip--left">
      <button class="k1-col-strip__btn" @click="leftOpen = true">›</button>
      <span class="k1-col-strip__label">Chat</span>
    </div>

    <!-- ── Col 2: center slot ── -->
    <FolderCenterPanel
      v-if="mode === 'folder'"
      :node-id="activeNodeId"
      @open-conversation="onSelectConversation"
    />
    <ConversationView v-else class="flex-1 min-w-0 overflow-hidden" />

    <!-- ── Col 3: right slot ── -->
    <template v-if="rightOpen">
      <ProjectDetailsPanel
        v-if="mode === 'folder'"
        :node-id="activeNodeId"
        @collapse="rightOpen = false"
      />
      <!-- Existing context panel in conversation mode -->
      <!-- TODO: wire real right-pane content here; add collapse toggle to tab bar -->
      <aside v-else class="k1-details-pane">
        <!-- Conversation context panel (existing functionality) -->
      </aside>
    </template>
    <div v-else class="k1-col-strip k1-col-strip--right">
      <button class="k1-col-strip__btn" @click="rightOpen = true">‹</button>
      <span class="k1-col-strip__label">{{ mode === 'folder' ? 'Details' : 'Context' }}</span>
    </div>

  </div>
</template>

<style scoped>
.k1-col-strip {
  flex-shrink: 0; width: 32px;
  display: flex; flex-direction: column;
  align-items: center; padding: 10px 0; gap: 14px;
  background: var(--bg-canvas);
}
.k1-col-strip--left  { border-right: 1px solid var(--border-1); }
.k1-col-strip--right { border-left:  1px solid var(--border-1); }
.k1-col-strip__btn {
  width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  color: var(--fg-5); cursor: pointer; border-radius: var(--radius-sharp);
  font-size: 13px; background: transparent; border: none;
  transition: color 150ms, background 150ms;
}
.k1-col-strip__btn:hover { color: var(--fg-2); background: var(--bg-elev-3); }
.k1-col-strip__label {
  writing-mode: vertical-rl;
  font-family: var(--font-mono); font-size: 9.5px;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--fg-6);
}
.k1-details-pane {
  width: 320px; flex-shrink: 0;
  border-left: 1px solid var(--border-1);
  display: flex; flex-direction: column;
  background: var(--bg-canvas);
}
</style>
