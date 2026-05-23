<script setup lang="ts">
/**
 * ConversationStateActions — Beacon wave 7, D1.
 *
 * Renders context-appropriate action buttons based on conversation state:
 *   pending  → "Approve" (→ open) + "Dismiss" (→ rejected)
 *   rejected → "Restore" (→ open)
 *   open     → overflow "⋮" button → "Mark as rejected" menu item
 *   closed   → overflow "⋮" button → "Mark as rejected" (spec §7.2: any conv)
 *
 * Emits events; parent is responsible for calling store.patch() / store.discard().
 * This keeps the component store-free and easy to test.
 */
import { ref } from 'vue'
import type { ConversationState } from '../../types/conversations'

const props = withDefaults(defineProps<{
  convId: string
  state: ConversationState
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  /** User approved a pending conversation — parent should PATCH state → 'open'. */
  approve: [convId: string]
  /**
   * User dismissed/rejected a conversation — parent should call store.discard().
   * Note: spec §7.2 requires a beacon_suppressions row on dismiss. When the
   * /api/conversations/{id}/discard endpoint ships (Phase 5), the store.discard()
   * method should call that instead of PATCH state=rejected.
   */
  dismiss: [convId: string]
  /** User restored a rejected conversation — parent should PATCH state → 'open'. */
  restore: [convId: string]
}>()

// Overflow menu open/closed (for open conversations)
const overflowOpen = ref(false)

function toggleOverflow() {
  overflowOpen.value = !overflowOpen.value
}

function closeOverflow() {
  overflowOpen.value = false
}

function onApprove() {
  if (props.loading) return
  emit('approve', props.convId)
}

function onDismiss() {
  if (props.loading) return
  closeOverflow()
  emit('dismiss', props.convId)
}

function onRestore() {
  if (props.loading) return
  emit('restore', props.convId)
}
</script>

<template>
  <!-- Pending: Approve + Dismiss side-by-side -->
  <template v-if="state === 'pending'">
    <div class="flex items-center gap-1">
      <button
        type="button"
        data-testid="btn-approve"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors"
        :class="loading
          ? 'opacity-50 cursor-not-allowed bg-[--bg-3] text-[--fg-4]'
          : 'bg-green-500 text-white hover:bg-green-600'"
        :disabled="loading"
        @click.stop="onApprove"
      >
        ✓ Approve
      </button>
      <button
        type="button"
        data-testid="btn-dismiss"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors"
        :class="loading
          ? 'opacity-50 cursor-not-allowed bg-[--bg-3] text-[--fg-4]'
          : 'bg-[--bg-3] text-[--fg-3] hover:bg-[--status-block-bg] hover:text-[--status-block-fg]'"
        :disabled="loading"
        @click.stop="onDismiss"
      >
        ✕ Dismiss
      </button>
    </div>
  </template>

  <!-- Rejected: Restore button -->
  <template v-else-if="state === 'rejected'">
    <button
      type="button"
      data-testid="btn-restore"
      class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors"
      :class="loading
        ? 'opacity-50 cursor-not-allowed bg-[--bg-3] text-[--fg-4]'
        : 'bg-[--bg-3] text-[--fg-3] hover:bg-[--accent] hover:text-[--accent-fg]'"
      :disabled="loading"
      @click.stop="onRestore"
    >
      ↩ Restore
    </button>
  </template>

  <!-- Open / closed: overflow menu with "Mark as rejected" (spec §7.2) -->
  <template v-else-if="state === 'open' || state === 'closed'">
    <div class="relative">
      <button
        type="button"
        data-testid="btn-overflow"
        class="px-1.5 py-0.5 rounded text-xs text-[--fg-4] hover:text-[--fg-2] hover:bg-[--bg-3] transition-colors"
        :aria-label="'Conversation options'"
        @click.stop="toggleOverflow"
      >
        ⋮
      </button>

      <!-- Overflow dropdown -->
      <div
        v-if="overflowOpen"
        class="absolute right-0 top-full mt-1 z-50 min-w-36 rounded-lg border border-[--border-1] bg-[--bg-elev-2] shadow-lg py-1"
        @click.stop
      >
        <button
          type="button"
          data-testid="btn-mark-rejected"
          class="w-full text-left px-3 py-1.5 text-xs text-[--fg-2] hover:bg-[--bg-elev-3] transition-colors"
          @click="onDismiss"
        >
          Mark as rejected
        </button>
      </div>
    </div>
  </template>


</template>
