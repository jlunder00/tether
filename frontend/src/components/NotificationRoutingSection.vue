<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../lib/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type NotifType = 'anchor_ping' | 'task_followup' | 'beacon' | 'meeting_event' | 'scheduling_update'
type RoutingMode = 'thread_by_key' | 'fixed' | 'bot_decides' | 'new_each'
type RoutingPriority = 'normal' | 'important' | 'urgent'
type RoutingChannel = 'telegram' | 'web' | 'discord' | 'slack'

interface RoutingEntry {
  mode: RoutingMode
  priority: RoutingPriority
  external: RoutingChannel[]
  key_template?: string
  conversation_id?: string
}

type NotificationRouting = Record<NotifType, RoutingEntry>

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NOTIF_TYPES: Array<{ key: NotifType; label: string }> = [
  { key: 'anchor_ping',       label: 'Anchor pings' },
  { key: 'task_followup',     label: 'Task follow-ups' },
  { key: 'beacon',            label: 'Beacon insights' },
  { key: 'meeting_event',     label: 'Meeting events' },
  { key: 'scheduling_update', label: 'Scheduling updates' },
]

const ROUTING_MODES: Array<{ value: RoutingMode; label: string; help: string }> = [
  {
    value: 'thread_by_key',
    label: 'Thread by key',
    help: 'Group related messages in a dedicated thread (e.g. per anchor + date).',
  },
  {
    value: 'fixed',
    label: 'Fixed conversation',
    help: 'Always routes to the system General conversation (auto-resolved).',
  },
  {
    value: 'bot_decides',
    label: 'Bot decides',
    help: 'Dispatcher picks the most relevant open conversation automatically.',
  },
  {
    value: 'new_each',
    label: 'New each time',
    help: 'Creates a fresh conversation for every notification.',
  },
]

const CHANNELS: Array<{ key: RoutingChannel; label: string; alwaysOn: boolean; comingSoon: boolean }> = [
  { key: 'telegram', label: 'Telegram', alwaysOn: false, comingSoon: false },
  { key: 'web',      label: 'Web',      alwaysOn: true,  comingSoon: false },
  { key: 'discord',  label: 'Discord',  alwaysOn: false, comingSoon: true  },
  { key: 'slack',    label: 'Slack',    alwaysOn: false, comingSoon: true  },
]

const PRIORITY_OPTIONS: Array<{ value: RoutingPriority; label: string }> = [
  { value: 'normal',    label: 'Normal' },
  { value: 'important', label: 'Important' },
  { value: 'urgent',    label: 'Urgent' },
]

const DEFAULT_ROUTING: NotificationRouting = {
  anchor_ping:       { mode: 'thread_by_key', priority: 'important', external: ['telegram'], key_template: 'anchor:{anchor_id}:{date}' },
  task_followup:     { mode: 'thread_by_key', priority: 'important', external: ['telegram'], key_template: 'anchor:{anchor_id}:{date}' },
  beacon:            { mode: 'bot_decides',   priority: 'normal',    external: ['web'] },
  meeting_event:     { mode: 'thread_by_key', priority: 'important', external: ['telegram', 'web'], key_template: 'meeting:{request_id}' },
  scheduling_update: { mode: 'fixed',         priority: 'normal',    external: ['web'] },
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const routing = ref<NotificationRouting>(structuredClone(DEFAULT_ROUTING))
const status = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const message = ref('')

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

onMounted(async () => {
  try {
    const resp = await api('/api/user/preferences')
    if (resp.ok) {
      const data = await resp.json()
      if (data.notification_routing) {
        routing.value = { ...DEFAULT_ROUTING, ...data.notification_routing }
      }
    }
  } catch {
    // Non-fatal: keep defaults
  }
})

// ---------------------------------------------------------------------------
// Save (called on any field change)
// ---------------------------------------------------------------------------

async function save() {
  status.value = 'saving'
  message.value = ''
  try {
    const resp = await api('/api/user/preferences', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notification_routing: routing.value }),
    })
    if (resp.ok) {
      status.value = 'saved'
      message.value = 'Saved.'
      setTimeout(() => { status.value = 'idle'; message.value = '' }, 1500)
    } else {
      status.value = 'error'
      message.value = 'Failed to save.'
    }
  } catch {
    status.value = 'error'
    message.value = 'Network error.'
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isChannelChecked(notifKey: NotifType, channel: RoutingChannel): boolean {
  const entry = routing.value[notifKey]
  if (channel === 'web') return true // always on
  return entry.external.includes(channel)
}

function onChannelChange(notifKey: NotifType, channel: RoutingChannel, checked: boolean) {
  if (channel === 'web') return // immutable
  const entry = routing.value[notifKey]
  if (checked) {
    if (!entry.external.includes(channel)) {
      entry.external = [...entry.external, channel]
    }
  } else {
    entry.external = entry.external.filter(c => c !== channel)
  }
  save()
}

function onModeChange() {
  save()
}

function onPriorityChange() {
  save()
}

function modeHelp(mode: RoutingMode): string {
  return ROUTING_MODES.find(m => m.value === mode)?.help ?? ''
}

function priorityClass(priority: RoutingPriority): string {
  if (priority === 'urgent')    return 'bg-[--status-urgent-bg] text-[--status-urgent-fg]'
  if (priority === 'important') return 'bg-[--status-important-bg] text-[--status-important-fg]'
  return ''
}
</script>

<template>
  <section class="mb-8" data-section="notification-routing">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">
      Notification Routing
    </h2>
    <div class="bg-[--bg-elev-1] rounded-xl divide-y divide-[--border-1]">
      <!-- One row per notification type -->
      <div
        v-for="notif in NOTIF_TYPES"
        :key="notif.key"
        :data-notif-type="notif.key"
        class="px-4 py-4 space-y-3"
      >
        <!-- Type label -->
        <div class="text-sm font-medium text-[--fg-1]">{{ notif.label }}</div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <!-- Routing mode -->
          <div>
            <label class="text-xs text-[--fg-4] mb-1 block">Mode</label>
            <select
              v-model="routing[notif.key].mode"
              :data-mode-select="notif.key"
              class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent]"
              @change="onModeChange()"
            >
              <option v-for="m in ROUTING_MODES" :key="m.value" :value="m.value">
                {{ m.label }}
              </option>
            </select>
            <p class="text-xs text-[--fg-5] mt-1 leading-snug">
              {{ modeHelp(routing[notif.key].mode) }}
            </p>
          </div>

          <!-- Priority -->
          <div>
            <label class="text-xs text-[--fg-4] mb-1 block">Priority</label>
            <select
              v-model="routing[notif.key].priority"
              :data-priority-select="notif.key"
              class="w-full rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] transition-colors"
              :class="priorityClass(routing[notif.key].priority) || 'bg-[--bg-elev-2] text-[--fg-1]'"
              @change="onPriorityChange()"
            >
              <option v-for="p in PRIORITY_OPTIONS" :key="p.value" :value="p.value">
                {{ p.label }}
              </option>
            </select>
          </div>
        </div>

        <!-- External channels -->
        <div>
          <div class="text-xs text-[--fg-4] mb-1.5">Channels</div>
          <div class="flex flex-wrap gap-3">
            <label
              v-for="ch in CHANNELS"
              :key="ch.key"
              class="flex items-center gap-1.5 text-xs cursor-pointer select-none"
              :class="ch.alwaysOn || ch.comingSoon ? 'opacity-60 cursor-not-allowed' : 'text-[--fg-2]'"
              :title="ch.comingSoon ? 'Coming soon' : ch.alwaysOn ? 'Always on — cannot disable web notifications' : undefined"
            >
              <input
                type="checkbox"
                :data-channel="ch.key"
                :checked="isChannelChecked(notif.key, ch.key)"
                :disabled="ch.alwaysOn || ch.comingSoon"
                class="accent-[--accent]"
                @change="onChannelChange(notif.key, ch.key, ($event.target as HTMLInputElement).checked)"
              />
              {{ ch.label }}
              <span v-if="ch.comingSoon" class="text-[--fg-5] text-[10px]">(soon)</span>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- Save status -->
    <p
      v-if="message"
      class="text-xs mt-2"
      :class="status === 'error' ? 'text-[--status-block-fg]' : 'text-[--status-done-fg]'"
    >
      {{ message }}
    </p>
  </section>
</template>
