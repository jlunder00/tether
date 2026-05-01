<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useApiKeysStore } from '../stores/apiKeys'

const store = useApiKeysStore()

// Track which key IDs currently show the inline revoke confirmation
const confirmingRevoke = ref<Set<string>>(new Set())

const newKeyName = ref('')
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  store.fetchKeys()
})

function startRevoke(id: string) {
  confirmingRevoke.value = new Set([...confirmingRevoke.value, id])
}

function cancelRevoke(id: string) {
  const next = new Set(confirmingRevoke.value)
  next.delete(id)
  confirmingRevoke.value = next
}

async function confirmRevoke(id: string) {
  await store.revokeKey(id)
  cancelRevoke(id)
}

async function handleCreate() {
  const name = newKeyName.value.trim()
  if (!name) return
  await store.createKey(name)
  if (!store.error) {
    newKeyName.value = ''
  }
}

async function copyKey() {
  if (!store.createdKey) return
  try {
    await navigator.clipboard.writeText(store.createdKey.raw_key)
    copied.value = true
    if (copiedTimer) clearTimeout(copiedTimer)
    copiedTimer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    // clipboard not available in test env
  }
}

/**
 * Format an ISO timestamp as a relative string like "2 days ago" or "just now".
 */
function formatRelative(isoString: string | null): string {
  if (!isoString) return 'never'
  const diff = Date.now() - new Date(isoString).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  return `${months}mo ago`
}
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">API Keys</h2>
    <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">

      <!-- One-time raw key display panel -->
      <div
        v-if="store.createdKey"
        class="border border-[--border-2] rounded-lg p-4 bg-[--bg-elev-2] space-y-3"
      >
        <div>
          <div class="text-sm font-medium text-[--fg-1] mb-1">
            Key created: <span class="text-[--fg-2]">{{ store.createdKey.name }}</span>
          </div>
          <p class="text-xs text-[--status-block-fg]">
            ⚠ Copy this key now — it will not be shown again.
          </p>
        </div>
        <code
          data-testid="apikeys-raw-key"
          class="block w-full font-mono text-xs bg-[--bg-elev-3] border border-[--border-1] rounded px-3 py-2 text-[--fg-1] break-all select-all"
        >{{ store.createdKey.raw_key }}</code>
        <div class="flex items-center gap-2">
          <button
            data-testid="apikeys-copy-btn"
            @click="copyKey"
            class="text-sm bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg px-4 py-2 transition-colors"
          >
            {{ copied ? 'Copied!' : 'Copy Key' }}
          </button>
          <button
            data-testid="apikeys-done-btn"
            @click="store.clearCreatedKey()"
            class="text-sm bg-[--bg-elev-3] hover:bg-[--bg-elev-2] text-[--fg-2] border border-[--border-1] font-medium rounded-lg px-4 py-2 transition-colors"
          >
            Done
          </button>
        </div>
      </div>

      <!-- Key list -->
      <template v-if="store.keys.length > 0">
        <div class="space-y-2">
          <div
            v-for="key in store.keys"
            :key="key.id"
            :data-testid="`apikeys-key-${key.id}`"
            class="flex items-center gap-3 rounded-lg bg-[--bg-elev-2] border border-[--border-1] px-3 py-2.5"
          >
            <!-- Key info -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium text-[--fg-1] truncate">{{ key.name }}</span>
                <code class="text-xs font-mono text-[--fg-3] bg-[--bg-elev-3] px-1.5 py-0.5 rounded">
                  {{ key.key_prefix }}...
                </code>
                <span
                  v-if="key.revoked_at"
                  class="text-xs font-medium text-[--status-block-fg] bg-[--bg-elev-3] px-1.5 py-0.5 rounded"
                >
                  Revoked
                </span>
              </div>
              <div class="flex items-center gap-3 mt-0.5 flex-wrap">
                <span class="text-xs text-[--fg-4]">
                  Created {{ formatRelative(key.created_at) }}
                </span>
                <span class="text-xs text-[--fg-4]">
                  Last used: {{ formatRelative(key.last_used_at) }}
                </span>
              </div>
            </div>

            <!-- Revoke confirmation or button -->
            <div class="shrink-0">
              <template v-if="key.revoked_at">
                <!-- Already revoked — no action available -->
              </template>
              <template v-else-if="confirmingRevoke.has(key.id)">
                <div class="flex items-center gap-2">
                  <span class="text-xs text-[--fg-3]">Revoke?</span>
                  <button
                    :data-testid="`apikeys-revoke-confirm-${key.id}`"
                    @click="confirmRevoke(key.id)"
                    class="text-xs text-red-400 hover:text-red-300 border border-red-400/30 hover:border-red-300/50 rounded-lg px-2.5 py-1.5 transition-colors"
                  >
                    Confirm
                  </button>
                  <button
                    @click="cancelRevoke(key.id)"
                    class="text-xs text-[--fg-4] hover:text-[--fg-2] border border-[--border-1] rounded-lg px-2 py-1.5 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </template>
              <button
                v-else
                :data-testid="`apikeys-revoke-${key.id}`"
                @click="startRevoke(key.id)"
                class="text-xs text-red-400 hover:text-red-300 border border-red-400/30 hover:border-red-300/50 rounded-lg px-2.5 py-1.5 transition-colors"
              >
                Revoke
              </button>
            </div>
          </div>
        </div>
      </template>

      <!-- Empty state -->
      <p v-else-if="!store.createdKey" class="text-sm text-[--fg-4]">
        No API keys yet. Create one below.
      </p>

      <!-- Error message -->
      <p v-if="store.error" class="text-sm text-[--status-block-fg]">{{ store.error }}</p>

      <!-- Create form -->
      <div v-if="!store.createdKey" class="flex gap-2 pt-1">
        <input
          v-model="newKeyName"
          data-testid="apikeys-create-input"
          type="text"
          placeholder="Key name (e.g. Claude Code)"
          class="flex-1 bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-indigo-500 placeholder:text-[--fg-5]"
          @keydown.enter="handleCreate"
        />
        <button
          data-testid="apikeys-create-submit"
          @click="handleCreate"
          :disabled="store.loading || !newKeyName.trim()"
          class="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg px-4 py-2 transition-colors shrink-0"
        >
          {{ store.loading ? '…' : 'Create' }}
        </button>
      </div>

    </div>
  </section>
</template>
