<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useContextStore } from '../../stores/context'
import type { ContextNode } from '../../stores/context'
import { useConversationsStore } from '../../stores/conversations'
import type { ConversationDetail } from '../../types/conversations'

defineProps<{ activeNodeId: string | null }>()
const emit = defineEmits<{
  'update:activeNodeId': [id: string | null]
  'open-conversation': [convId: string]
  'collapse': []
}>()

const contextStore = useContextStore()
const conversationsStore = useConversationsStore()

// ── Core state ─────────────────────────────────────────────────────────────

// Track expanded nodes
const expandedNodes = ref<Set<string>>(new Set())
// Track which node is being dragged over (for drop zone highlight)
const dragOverNodeId = ref<string | null>(null)
// Map of nodeId → conversations fetched for that node
const convsByNode = ref<Map<string, ConversationDetail[]>>(new Map())

// ── Editing state (K1-PR2) ─────────────────────────────────────────────────

// Inline rename
const renamingNodeId = ref<string | null>(null)
const renameValue = ref<string>('')
const renameInputRef = ref<HTMLInputElement | null>(null)

// Inline create (parentId string = child; 'root' = root level; null = not creating)
const creatingUnderNodeId = ref<string | null>(null)
const newFolderName = ref<string>('')
const createInputRef = ref<HTMLInputElement | null>(null)

// Delete confirmation
const deletingNode = ref<ContextNode | null>(null)
const deleteCancelBtnRef = ref<HTMLButtonElement | null>(null)

onMounted(() => {
  contextStore.fetchRootNodes()
})

// ── Selection ──────────────────────────────────────────────────────────────

function selectAll() {
  emit('update:activeNodeId', null)
}

function selectNode(nodeId: string) {
  emit('update:activeNodeId', nodeId)
}

// ── Expand / collapse ──────────────────────────────────────────────────────

async function toggleExpand(node: ContextNode, evt: Event) {
  evt.stopPropagation()
  const id = node.id
  if (expandedNodes.value.has(id)) {
    expandedNodes.value = new Set([...expandedNodes.value].filter(x => x !== id))
  } else {
    expandedNodes.value = new Set([...expandedNodes.value, id])
    await contextStore.fetchChildren(id)
    await conversationsStore.refresh({ context_node_id: id })
    convsByNode.value = new Map(convsByNode.value).set(
      id,
      conversationsStore.list.filter(c => c.context_node_id === id),
    )
  }
}

function hasChildren(node: ContextNode): boolean {
  if (node.children_count === undefined) return true
  return node.children_count > 0
}

// ── Inline rename ──────────────────────────────────────────────────────────

function startRename(node: ContextNode, evt: Event) {
  evt.stopPropagation()
  renamingNodeId.value = node.id
  renameValue.value = node.name
  nextTick(() => renameInputRef.value?.focus())
}

function commitRename(nodeId: string, originalName: string) {
  const trimmed = renameValue.value.trim()
  renamingNodeId.value = null
  if (!trimmed || trimmed === originalName) return
  contextStore.patchNode(nodeId, { name: trimmed })
}

function cancelRename() {
  // Zero renameValue so that if the browser fires blur on DOM teardown,
  // commitRename's !trimmed guard treats it as a no-op.
  renameValue.value = ''
  renamingNodeId.value = null
}

function onRenameKeydown(nodeId: string, originalName: string, evt: KeyboardEvent) {
  if (evt.key === 'Enter') { evt.preventDefault(); commitRename(nodeId, originalName) }
  if (evt.key === 'Escape') { evt.preventDefault(); cancelRename() }
}

// ── Create folder ──────────────────────────────────────────────────────────

// parentId: node id string → child of that node; 'root' → root-level folder
function startCreate(parentId: string | 'root', evt: Event) {
  evt.stopPropagation()
  creatingUnderNodeId.value = parentId
  newFolderName.value = ''
  nextTick(() => createInputRef.value?.focus())
}

function commitCreate() {
  const name = newFolderName.value.trim()
  const parentId = creatingUnderNodeId.value
  creatingUnderNodeId.value = null
  if (!name || !parentId) return
  contextStore.createNode(parentId === 'root' ? null : parentId, name)
}

function cancelCreate() {
  creatingUnderNodeId.value = null
}

function onCreateKeydown(evt: KeyboardEvent) {
  if (evt.key === 'Enter') { evt.preventDefault(); commitCreate() }
  if (evt.key === 'Escape') { evt.preventDefault(); cancelCreate() }
}

// ── Delete folder ──────────────────────────────────────────────────────────

function startDelete(node: ContextNode, evt: Event) {
  evt.stopPropagation()
  deletingNode.value = node
  nextTick(() => deleteCancelBtnRef.value?.focus())
}

async function confirmDelete() {
  if (!deletingNode.value) return
  const nodeId = deletingNode.value.id
  deletingNode.value = null
  await contextStore.deleteNode(nodeId)
}

function cancelDelete() {
  deletingNode.value = null
}

// ── Drag: conversation onto folder (existing) ──────────────────────────────

function onConvLeafDragStart(conv: ConversationDetail, evt: DragEvent) {
  evt.dataTransfer?.setData('text/plain', JSON.stringify({ conversationId: conv.id }))
}

// ── Drag: folder reparent (K1-PR2) ────────────────────────────────────────

// Uses distinct MIME 'application/x-tether-folder' to avoid conflict with
// the conversation drag payload ('text/plain' + {conversationId}).
function onFolderDragStart(nodeId: string, evt: DragEvent) {
  evt.dataTransfer?.setData(
    'application/x-tether-folder',
    JSON.stringify({ folderId: nodeId }),
  )
  if (evt.dataTransfer) evt.dataTransfer.effectAllowed = 'move'
}

function isFolderDrag(evt: DragEvent): boolean {
  // types is a DOMStringList in browsers; may be an array or absent in test environments
  const types = evt.dataTransfer?.types
  return (types != null && typeof types.includes === 'function')
    ? types.includes('application/x-tether-folder')
    : false
}

function onDragOver(nodeId: string, evt: DragEvent) {
  evt.preventDefault()
  dragOverNodeId.value = nodeId
}

function onDragLeave(nodeId: string) {
  if (dragOverNodeId.value === nodeId) {
    dragOverNodeId.value = null
  }
}

// Handles drops on folder rows — dispatches to either folder-reparent or conv-assign.
async function onDrop(nodeId: string, evt: DragEvent) {
  evt.preventDefault()
  dragOverNodeId.value = null

  if (isFolderDrag(evt)) {
    const raw = evt.dataTransfer?.getData('application/x-tether-folder') ?? ''
    try {
      const { folderId } = JSON.parse(raw)
      // Prevent self-drop (cycle guard: descendent check is backend-enforced)
      if (folderId && folderId !== nodeId) {
        await contextStore.moveNode(folderId, nodeId)
      }
    } catch {
      // ignore malformed
    }
    return
  }

  // Fallback: conversation drop
  const raw = evt.dataTransfer?.getData('text/plain')
  if (!raw) return
  try {
    const { conversationId } = JSON.parse(raw)
    if (conversationId) {
      await conversationsStore.assignNode(conversationId, nodeId)
    }
  } catch {
    // ignore malformed data
  }
}

// Root drop zone — folder drag only (conversations have no "unassign" meaning here)
async function onRootDrop(evt: DragEvent) {
  evt.preventDefault()
  dragOverNodeId.value = null
  if (!isFolderDrag(evt)) return
  const raw = evt.dataTransfer?.getData('application/x-tether-folder') ?? ''
  try {
    const { folderId } = JSON.parse(raw)
    if (folderId) {
      await contextStore.moveNode(folderId, null)
    }
  } catch {
    // ignore
  }
}

function onRootDragOver(evt: DragEvent) {
  if (isFolderDrag(evt)) evt.preventDefault()
}

// ── Misc helpers ───────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  return `${Math.floor(hrs / 24)}d`
}

function startNewChat(nodeId: string) {
  emit('update:activeNodeId', nodeId)
}
</script>

<template>
  <div
    class="sidebar-root flex flex-col h-full text-sm"
    style="width:240px;flex-shrink:0;border-right:1px solid var(--border-1);"
  >

    <!-- ── Header ── -->
    <div class="px-3 py-2.5 border-b border-[--border-1] flex-shrink-0 flex items-center justify-between">
      <span class="font-semibold text-[10px] text-[--fg-5] uppercase tracking-widest font-mono">Chat</span>
      <div class="flex items-center gap-1">
        <button
          type="button"
          class="sidebar-icon-btn"
          title="New chat"
          @click="emit('update:activeNodeId', null)"
        >+</button>
        <button
          data-testid="sidebar-collapse-btn"
          type="button"
          class="sidebar-icon-btn"
          title="Collapse"
          @click="emit('collapse')"
        >‹</button>
      </div>
    </div>

    <!-- ── All conversations (also root folder-drag drop zone) ── -->
    <div
      data-testid="all-item"
      class="flex items-center px-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors"
      :class="activeNodeId === null ? 'bg-[--bg-elev-3] font-medium' : ''"
      @click="selectAll"
      @dragover="onRootDragOver"
      @drop="onRootDrop"
    >
      <span class="text-[--fg-2] text-xs">All conversations</span>
    </div>

    <!-- ── Node tree ── -->
    <div class="flex-1 overflow-y-auto">
      <template v-for="node in contextStore.rootNodes" :key="node.id">

        <!-- Root node row -->
        <div
          :data-testid="`drop-zone-${node.id}`"
          class="node-row flex items-center gap-1 px-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors group"
          :class="[
            activeNodeId === node.id ? 'bg-[--bg-elev-3] font-medium' : '',
            dragOverNodeId === node.id ? 'drag-over' : '',
          ]"
          draggable="true"
          @dragstart="onFolderDragStart(node.id, $event)"
          @dragover="onDragOver(node.id, $event)"
          @dragleave="onDragLeave(node.id)"
          @drop="onDrop(node.id, $event)"
        >
          <!-- Expand chevron -->
          <button
            v-if="hasChildren(node)"
            :data-testid="`expand-chevron-${node.id}`"
            type="button"
            class="w-4 h-4 flex items-center justify-center text-[--fg-4] hover:text-[--fg-1] flex-shrink-0"
            @click.stop="toggleExpand(node, $event)"
          >
            <svg
              class="w-3 h-3 transition-transform"
              :class="expandedNodes.has(node.id) ? 'rotate-90' : ''"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <span v-else class="w-4 flex-shrink-0" />

          <!-- Name: rename input or clickable span -->
          <input
            v-if="renamingNodeId === node.id"
            :ref="(el) => { if (el) renameInputRef = el as HTMLInputElement }"
            :data-testid="`rename-input-${node.id}`"
            class="rename-input flex-1 text-xs"
            :value="renameValue"
            @input="renameValue = ($event.target as HTMLInputElement).value"
            @keydown="onRenameKeydown(node.id, node.name, $event)"
            @blur="commitRename(node.id, node.name)"
            @click.stop
          />
          <span
            v-else
            :data-testid="`node-row-${node.id}`"
            class="text-[--fg-2] text-xs truncate flex-1"
            @click="selectNode(node.id)"
            @dblclick.stop="startRename(node, $event)"
          >
            {{ node.name }}
          </span>

          <!-- Action buttons (visible on group hover) -->
          <div class="node-actions flex items-center gap-0.5 flex-shrink-0">
            <button
              :data-testid="`create-child-btn-${node.id}`"
              type="button"
              class="node-action-btn"
              title="New subfolder"
              @click.stop="startCreate(node.id, $event)"
            >+</button>
            <button
              :data-testid="`delete-btn-${node.id}`"
              type="button"
              class="node-action-btn node-action-btn--danger"
              title="Delete folder"
              @click.stop="startDelete(node, $event)"
            >
              <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <path d="M2 4h12M6 4V2h4v2M5 4l1 10h4l1-10"/>
              </svg>
            </button>
          </div>
        </div>

        <!-- Inline create-child input (appears after the node row) -->
        <div
          v-if="creatingUnderNodeId === node.id"
          class="create-input-row flex items-center pl-8 pr-3 py-1"
        >
          <input
            :ref="(el) => { if (el) createInputRef = el as HTMLInputElement }"
            :data-testid="`create-input-${node.id}`"
            class="create-input flex-1 text-xs"
            v-model="newFolderName"
            placeholder="Folder name…"
            @keydown="onCreateKeydown"
            @blur="commitCreate"
          />
        </div>

        <!-- Children + conversation leaves (when expanded) -->
        <template v-if="expandedNodes.has(node.id)">

          <!-- Child folder nodes (indented) -->
          <div
            v-for="child in contextStore.childrenOf(node.id)"
            :key="child.id"
            :data-testid="`drop-zone-${child.id}`"
            class="node-row flex items-center gap-1 pl-8 pr-3 py-2 cursor-pointer hover:bg-[--bg-2] transition-colors group"
            :class="[
              activeNodeId === child.id ? 'bg-[--bg-elev-3] font-medium' : '',
              dragOverNodeId === child.id ? 'drag-over' : '',
            ]"
            draggable="true"
            @dragstart="onFolderDragStart(child.id, $event)"
            @dragover="onDragOver(child.id, $event)"
            @dragleave="onDragLeave(child.id)"
            @drop="onDrop(child.id, $event)"
          >
            <!-- Name: rename input or span -->
            <input
              v-if="renamingNodeId === child.id"
              :ref="(el) => { if (el) renameInputRef = el as HTMLInputElement }"
              :data-testid="`rename-input-${child.id}`"
              class="rename-input flex-1 text-xs"
              :value="renameValue"
              @input="renameValue = ($event.target as HTMLInputElement).value"
              @keydown="onRenameKeydown(child.id, child.name, $event)"
              @blur="commitRename(child.id, child.name)"
              @click.stop
            />
            <span
              v-else
              :data-testid="`node-row-${child.id}`"
              class="text-[--fg-2] text-xs truncate flex-1"
              @click="selectNode(child.id)"
              @dblclick.stop="startRename(child, $event)"
            >
              {{ child.name }}
            </span>

            <!-- Action buttons -->
            <div class="node-actions flex items-center gap-0.5 flex-shrink-0">
              <button
                :data-testid="`create-child-btn-${child.id}`"
                type="button"
                class="node-action-btn"
                title="New subfolder"
                @click.stop="startCreate(child.id, $event)"
              >+</button>
              <button
                :data-testid="`delete-btn-${child.id}`"
                type="button"
                class="node-action-btn node-action-btn--danger"
                title="Delete folder"
                @click.stop="startDelete(child, $event)"
              >
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                  <path d="M2 4h12M6 4V2h4v2M5 4l1 10h4l1-10"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Conversation leaf items -->
          <div
            v-for="conv in convsByNode.get(node.id) ?? []"
            :key="conv.id"
            :data-testid="`conv-leaf-${conv.id}`"
            class="tree-conv-item"
            :class="conversationsStore.selectedId === conv.id ? 'tree-conv-item--active' : ''"
            draggable="true"
            @click="emit('open-conversation', conv.id)"
            @dragstart="onConvLeafDragStart(conv, $event)"
          >
            <span class="tree-conv-dot" />
            <span class="flex-1 truncate text-xs">{{ conv.name }}</span>
            <span class="tree-conv-ts">{{ relativeTime(conv.last_message_at) }}</span>
          </div>

          <!-- + New chat affordance -->
          <div class="tree-new-chat" @click="startNewChat(node.id)">
            + New chat
          </div>
        </template>

      </template>

      <!-- ── New root folder affordance ── -->
      <div
        v-if="creatingUnderNodeId === 'root'"
        class="create-input-row flex items-center px-3 py-1"
      >
        <input
          :ref="(el) => { if (el) createInputRef = el as HTMLInputElement }"
          data-testid="create-input-root"
          class="create-input flex-1 text-xs"
          v-model="newFolderName"
          placeholder="New folder name…"
          @keydown="onCreateKeydown"
          @blur="commitCreate"
        />
      </div>
      <div
        v-else
        data-testid="create-root-btn"
        class="tree-new-root"
        @click="startCreate('root', $event)"
      >
        + New folder
      </div>
    </div>

    <!-- ── Delete confirmation overlay ── -->
    <div
      v-if="deletingNode"
      data-testid="delete-confirm-dialog"
      class="delete-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-dialog-title"
      @click.self="cancelDelete"
      @keydown.escape.stop="cancelDelete"
    >
      <div class="delete-dialog">
        <p id="delete-dialog-title" class="delete-dialog__msg">
          Delete '{{ deletingNode.name }}'?
          <template v-if="(deletingNode.children_count ?? 0) > 0">
            This will delete {{ deletingNode.children_count }}
            {{ deletingNode.children_count === 1 ? 'subfolder' : 'subfolders' }}.
          </template>
          Any conversations inside will move to All conversations.
        </p>
        <div class="delete-dialog__actions">
          <button
            :ref="(el) => { if (el) deleteCancelBtnRef = el as HTMLButtonElement }"
            data-testid="delete-confirm-cancel"
            type="button"
            class="delete-btn delete-btn--cancel"
            @click="cancelDelete"
          >Cancel</button>
          <button
            data-testid="delete-confirm-ok"
            type="button"
            class="delete-btn delete-btn--ok"
            @click="confirmDelete"
          >Delete</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ── Tree items ── */
.tree-conv-item {
  display: flex; align-items: center; gap: 8px;
  padding: 5px 10px 5px 48px;
  font-size: 12px; color: var(--fg-3);
  cursor: pointer; min-height: 26px;
  transition: background 150ms;
}
.tree-conv-item:hover         { background: var(--bg-elev-2); }
.tree-conv-item--active       { background: var(--bg-elev-3); color: var(--fg-1); }

.tree-conv-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent); flex-shrink: 0;
  visibility: hidden;
}

.tree-conv-ts {
  font-family: var(--font-mono); font-size: 9.5px;
  color: var(--fg-5); flex-shrink: 0; padding-right: 4px;
}

.tree-new-chat {
  display: flex; align-items: center; gap: 5px;
  padding: 4px 10px 6px 48px;
  font-family: var(--font-mono); font-size: 11px;
  color: var(--accent); cursor: pointer; opacity: 0.7;
  transition: opacity 150ms;
}
.tree-new-chat:hover { opacity: 1; }

.tree-new-root {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 12px;
  font-family: var(--font-mono); font-size: 11px;
  color: var(--fg-5); cursor: pointer; opacity: 0.5;
  transition: opacity 150ms, color 150ms;
}
.tree-new-root:hover { opacity: 1; color: var(--accent); }

/* ── Sidebar icon buttons ── */
.sidebar-icon-btn {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent; cursor: pointer;
  border-radius: var(--radius-sharp); color: var(--fg-4);
  transition: background 150ms, color 150ms;
}
.sidebar-icon-btn:hover { background: var(--bg-elev-3); color: var(--fg-2); }

/* ── Drag-over highlight ── */
.drag-over {
  outline: 1px solid var(--accent-soft);
  outline-offset: -1px;
  background: var(--accent-veil);
}

/* ── Node action buttons (hover-visible on parent .group) ── */
.node-actions {
  opacity: 0;
  transition: opacity 100ms;
}
.node-row:hover .node-actions,
.node-row:focus-within .node-actions {
  opacity: 1;
}

.node-action-btn {
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent; cursor: pointer;
  border-radius: var(--radius-sharp); color: var(--fg-5);
  font-size: 12px;
  transition: background 100ms, color 100ms;
}
.node-action-btn:hover { background: var(--bg-elev-3); color: var(--fg-2); }
.node-action-btn--danger:hover { background: var(--status-block-bg); color: var(--status-block-fg, var(--fg-1)); }

/* ── Rename input ── */
.rename-input {
  background: var(--bg-elev-2);
  border: 1px solid var(--accent-soft);
  border-radius: var(--radius-sharp);
  color: var(--fg-1);
  padding: 1px 5px;
  outline: none;
  font-family: var(--font-sans);
  min-width: 0;
}

/* ── Create input ── */
.create-input-row {
  background: var(--bg-elev-1);
}
.create-input {
  background: var(--bg-elev-2);
  border: 1px solid var(--accent-soft);
  border-radius: var(--radius-sharp);
  color: var(--fg-1);
  padding: 2px 6px;
  outline: none;
  font-family: var(--font-sans);
  width: 100%;
  box-sizing: border-box;
}

/* ── Delete confirmation overlay ── */
.delete-overlay {
  position: absolute;
  inset: 0;
  background: var(--bg-canvas);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
  padding: 16px;
}

.delete-dialog {
  background: var(--bg-elev-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-soft);
  padding: 16px;
  max-width: 200px;
  width: 100%;
  box-shadow: var(--shadow-pop);
}

.delete-dialog__msg {
  font-size: 12px;
  color: var(--fg-2);
  line-height: 1.5;
  margin-bottom: 12px;
}

.delete-dialog__actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}

.delete-btn {
  padding: 4px 10px;
  font-size: 11.5px;
  border-radius: var(--radius-sharp);
  border: 1px solid var(--border-1);
  cursor: pointer;
  font-family: var(--font-sans);
  transition: background 150ms, color 150ms;
}

.delete-btn--cancel {
  background: transparent;
  color: var(--fg-3);
}
.delete-btn--cancel:hover { background: var(--bg-elev-3); color: var(--fg-1); }

.delete-btn--ok {
  background: var(--status-block-bg, color-mix(in srgb, var(--fg-1) 8%, transparent));
  color: var(--fg-1);
  border-color: transparent;
}
.delete-btn--ok:hover { opacity: 0.85; }
</style>
