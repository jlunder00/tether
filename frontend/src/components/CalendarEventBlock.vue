<script setup lang="ts">
import type { CalendarEvent } from '../types/events'

const props = defineProps<{
  event: CalendarEvent
  topPx: number
  heightPx: number
  leftPercent?: number
  widthPercent?: number
  resolvedColor?: string
}>()

const emit = defineEmits<{
  (e: 'click', event: CalendarEvent): void
  (e: 'mousedown', ev: MouseEvent): void
}>()

function defaultColor(event: CalendarEvent): string {
  if (event.source !== 'tether') return '#4285f4'
  return event.color ?? '#6366f1'
}
</script>

<template>
  <div
    class="absolute rounded overflow-hidden text-xs px-1.5 py-0.5 cursor-grab shadow-md hover:brightness-110 transition-all z-10"
    :style="{
      top: `${topPx}px`,
      height: `${heightPx}px`,
      left: `calc(${props.leftPercent ?? 0}% + ${(props.widthPercent ?? 100) * 0.05}% + 2px)`,
      width: `calc(${(props.widthPercent ?? 100) * 0.9}% - 4px)`,
      backgroundColor: props.resolvedColor ?? defaultColor(event),
      borderLeft: '3px solid ' + (props.resolvedColor ?? defaultColor(event)),
      opacity: event.source !== 'tether' ? 0.75 : 0.92,
    }"
    @click.stop="emit('click', event)"
    @mousedown.stop="(ev) => emit('mousedown', ev)"
  >
    <div class="flex items-center gap-1 truncate pointer-events-none">
      <span
        v-if="event.source !== 'tether'"
        data-testid="gcal-badge"
        class="text-[9px] bg-black/20 rounded px-0.5 flex-shrink-0"
        :title="event.source === 'google_calendar' ? 'Synced from Google Calendar' : 'Synced from external calendar'"
      >
        {{ event.source === 'google_calendar' ? 'G' : '↗' }}
      </span>
      <span
        v-if="event.is_recurring || event.is_occurrence"
        data-testid="recurring-indicator"
        class="text-[9px] flex-shrink-0 opacity-80"
        title="Recurring event"
      >↻</span>
      <span class="truncate font-medium text-[--accent-fg]">{{ event.title }}</span>
    </div>
  </div>
</template>
