<script setup lang="ts">
import { onMounted } from 'vue'
import { useAgentSettingsStore } from '../stores/agentSettings'

const store = useAgentSettingsStore()

onMounted(() => store.fetchSettings())

function toggleAutoApprove() {
  store.setAutoApprove(!store.autoApproveUserActions)
}

function toggleDevMode() {
  store.setDevMode(!store.devModeShowRawTools)
}
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">Agent Behaviour</h2>
    <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">

      <!-- Auto-approve agent actions -->
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm text-[--fg-1]">Auto-approve agent actions</div>
          <div class="text-xs text-[--fg-4]">
            When on, the agent doesn't ask permission before writing to your data.
            Use only if you trust the agent fully.
          </div>
        </div>
        <button
          role="switch"
          type="button"
          :aria-checked="store.autoApproveUserActions"
          :class="store.autoApproveUserActions ? 'bg-[--accent]' : 'bg-[--bg-elev-3]'"
          class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ml-4"
          @click="toggleAutoApprove"
        >
          <span
            :class="store.autoApproveUserActions ? 'translate-x-5' : 'translate-x-0.5'"
            class="inline-block w-5 h-5 bg-white rounded-full transition-transform transform mt-0.5"
          />
        </button>
      </div>

      <!-- Show raw tool names (dev mode) -->
      <div class="flex items-center justify-between">
        <div>
          <div class="text-sm text-[--fg-1]">Show raw tool names</div>
          <div class="text-xs text-[--fg-4]">
            Developer mode: show raw tool names alongside friendly action descriptions
            in chat. Off by default for end users.
          </div>
        </div>
        <button
          role="switch"
          type="button"
          :aria-checked="store.devModeShowRawTools"
          :class="store.devModeShowRawTools ? 'bg-[--accent]' : 'bg-[--bg-elev-3]'"
          class="relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ml-4"
          @click="toggleDevMode"
        >
          <span
            :class="store.devModeShowRawTools ? 'translate-x-5' : 'translate-x-0.5'"
            class="inline-block w-5 h-5 bg-white rounded-full transition-transform transform mt-0.5"
          />
        </button>
      </div>

    </div>
  </section>
</template>
