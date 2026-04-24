<script setup lang="ts">
import type { CalendarEvent } from '../types/events'

const props = defineProps<{
  event: CalendarEvent
  topPx: number
  heightPx: number
}>()

const emit = defineEmits<{
  (e: 'click', event: CalendarEvent): void
  (e: 'mousedown', ev: MouseEvent): void
}>()

function eventColor(event: CalendarEvent): string {
  if (event.source !== 'tether') return '#4285f4' // Google blue for synced
  return event.color ?? '#6366f1' // indigo default
}
</script>

<template>
  <div
    class="absolute inset-x-1 rounded overflow-hidden text-xs px-1.5 py-0.5 cursor-grab shadow-md hover:brightness-110 transition-all z-10"
    :style="{
      top: `${topPx}px`,
      height: `${heightPx}px`,
      backgroundColor: eventColor(event),
      opacity: event.source !== 'tether' ? 0.75 : 1,
    }"
    @click.stop="emit('click', event)"
    @mousedown.stop="(ev) => emit('mousedown', ev)"
  >
    <div class="flex items-center gap-1 truncate pointer-events-none">
      <!-- Provider badge for synced events -->
      <span
        v-if="event.source !== 'tether'"
        data-testid="gcal-badge"
        class="text-[9px] bg-black/20 rounded px-0.5 flex-shrink-0"
        :title="event.source === 'google_calendar' ? 'Synced from Google Calendar' : 'Synced from external calendar'"
      >
        {{ event.source === 'google_calendar' ? 'G' : '↗' }}
      </span>
      <span class="truncate font-medium text-white">{{ event.title }}</span>
    </div>
  </div>
</template>
