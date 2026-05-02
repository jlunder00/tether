<script setup lang="ts">
defineProps<{
  date: string
  taskCount: number
  isToday: boolean
}>()

const emit = defineEmits<{
  (e: 'day-click', date: string): void
}>()
</script>

<template>
  <div
    :data-date="date"
    class="relative flex flex-col items-center justify-start p-0.5 rounded cursor-pointer min-h-[28px] transition-colors select-none hover:bg-[--bg-elev-2]"
    @click="emit('day-click', date)"
  >
    <!-- Day number -->
    <span
      class="text-[11px] font-medium leading-tight"
      :class="isToday ? 'text-[--accent] font-bold' : 'text-[--fg-3]'"
    >{{ new Date(date + 'T12:00:00').getDate() }}</span>

    <!-- Task count dot indicator -->
    <span
      v-if="taskCount > 0"
      class="text-[9px] text-[--fg-5] leading-none"
    >{{ taskCount }}</span>
  </div>
</template>
