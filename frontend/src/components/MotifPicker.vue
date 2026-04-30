<template>
  <div class="flex gap-2 items-center">
    <span class="text-xs" style="color: var(--fg-4)">Color</span>
    <button
      v-for="slot in MOTIF_SLOTS"
      :key="slot"
      type="button"
      data-testid="motif-dot"
      :data-slot="slot"
      class="w-5 h-5 rounded-full border-2 transition-all"
      :style="{
        background: `var(--motif-${slot})`,
        borderColor: modelValue === slot ? `var(--motif-${slot})` : 'transparent',
        outline: modelValue === slot ? `2px solid var(--motif-${slot})` : 'none',
        outlineOffset: '2px'
      }"
      :title="slot"
      @click.stop="$emit('update:modelValue', slot)"
    />
  </div>
</template>

<script setup lang="ts">
const MOTIF_SLOTS = ['anchor','focus','calm','energy','care','flow','dusk','quiet','light','dark'] as const
export type MotifSlot = typeof MOTIF_SLOTS[number]

defineProps<{ modelValue: MotifSlot | null | undefined }>()
defineEmits<{ 'update:modelValue': [slot: MotifSlot] }>()
</script>
