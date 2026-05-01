<script setup lang="ts">
import { ref, onMounted } from 'vue'

interface InviteToken {
  token: string
  created_at: string
  used_by: string | null
}

const invites = ref<InviteToken[]>([])
const inviteLink = ref('')
const inviteError = ref('')
const inviteLoading = ref(false)
const invitesCopied = ref(false)
const listLoading = ref(false)
const listError = ref('')

async function fetchInvites() {
  listLoading.value = true
  listError.value = ''
  try {
    const resp = await fetch('/auth/invites', { credentials: 'include' })
    if (resp.ok) {
      invites.value = await resp.json()
    } else {
      listError.value = 'Failed to load invites.'
    }
  } catch {
    listError.value = 'Network error.'
  } finally {
    listLoading.value = false
  }
}

async function generateInvite() {
  inviteLoading.value = true
  inviteError.value = ''
  inviteLink.value = ''
  try {
    const resp = await fetch('/auth/invite', {
      method: 'POST',
      credentials: 'include',
    })
    if (resp.ok) {
      const data = await resp.json()
      const token = data.token
      inviteLink.value = `${window.location.origin}/register?invite=${token}`
      await fetchInvites()
    } else {
      const data = await resp.json().catch(() => ({}))
      inviteError.value = data.detail || 'Failed to generate invite.'
    }
  } catch {
    inviteError.value = 'Network error.'
  } finally {
    inviteLoading.value = false
  }
}

async function copyInviteLink() {
  if (!inviteLink.value) return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    invitesCopied.value = true
    setTimeout(() => { invitesCopied.value = false }, 2000)
  } catch {
    // fallback: select the text
  }
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

onMounted(fetchInvites)
</script>

<template>
  <div class="min-h-screen bg-[--bg-canvas] text-[--fg-1] p-6">
    <div class="max-w-lg mx-auto">
      <!-- Header -->
      <div class="flex items-center gap-3 mb-8">
        <router-link to="/" class="text-[--fg-4] hover:text-[--fg-1] text-sm">← Back</router-link>
        <h1 class="text-xl font-bold">Admin</h1>
      </div>

      <!-- Generate Invite -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Generate Invite</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4">
          <button
            @click="generateInvite"
            :disabled="inviteLoading"
            class="bg-[--accent] hover:opacity-90 disabled:opacity-50 text-[--accent-fg] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
          >
            {{ inviteLoading ? 'Generating…' : 'Generate Invite Link' }}
          </button>

          <div v-if="inviteError" class="mt-3 text-[--status-block-fg] text-sm">{{ inviteError }}</div>

          <div v-if="inviteLink" class="mt-3">
            <div class="flex items-center gap-2">
              <input
                :value="inviteLink"
                readonly
                class="flex-1 bg-[--bg-elev-2] text-[--fg-1] text-sm rounded-lg px-3 py-2 border border-[--border-1] focus:outline-none font-mono truncate"
              />
              <button
                @click="copyInviteLink"
                class="bg-[--bg-elev-2] hover:bg-[--bg-elev-3] text-[--fg-1] text-sm rounded-lg px-3 py-2 border border-[--border-1] transition-colors whitespace-nowrap"
              >
                {{ invitesCopied ? 'Copied!' : 'Copy' }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Invite Tokens List -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Invite Tokens</h2>
        <div class="bg-[--bg-elev-1] rounded-xl overflow-hidden">
          <div v-if="listLoading" class="p-4 text-[--fg-4] text-sm">Loading…</div>
          <div v-else-if="listError" class="p-4 text-[--status-block-fg] text-sm">{{ listError }}</div>
          <div v-else-if="invites.length === 0" class="p-4 text-[--fg-4] text-sm">No invites yet.</div>
          <div v-else>
            <div
              v-for="invite in invites"
              :key="invite.token"
              class="flex items-center justify-between px-4 py-3 border-b border-[--border-1] last:border-0"
            >
              <div>
                <div class="font-mono text-sm text-[--fg-2]">{{ invite.token.slice(0, 8) }}…</div>
                <div class="text-xs text-[--fg-4] mt-0.5">{{ formatDate(invite.created_at) }}</div>
              </div>
              <span
                :class="invite.used_by ? 'bg-[--bg-elev-2] text-[--fg-4]' : 'bg-[--status-done-bg] text-[--status-done-fg]'"
                class="text-xs font-medium px-2 py-0.5 rounded-full"
              >
                {{ invite.used_by ? 'Used' : 'Unused' }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- User Management -->
      <section class="mb-8">
        <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Users</h2>
        <div class="bg-[--bg-elev-1] rounded-xl p-4">
          <p class="text-sm text-[--fg-4]">User management coming soon.</p>
        </div>
      </section>
    </div>
  </div>
</template>
