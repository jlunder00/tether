<script setup lang="ts">
import { ref, computed } from 'vue'

const props = withDefaults(defineProps<{
  label: string
  color?: string
  collapsible?: boolean
  level?: number  // 0 = top-level (anchor/context), 1 = nested (milestone)
  stickyOffset?: number // px offset for sticky headers (e.g., nav bar height)
}>(), {
  collapsible: true,
  level: 0,
  stickyOffset: 52,
})

const emit = defineEmits<{ (e: 'header-click'): void }>()

const collapsed = ref(false)

// Sidebar line color: use the group's color if provided, else neutral fg-5 placeholder
// (real motif field is coming via a separate backend stream).
const railColor = computed(() => props.color || 'var(--fg-5)')

const stickyTop = computed(() => {
  if (props.level === 0) return `${props.stickyOffset}px`
  return `${props.stickyOffset + 28}px`
})
</script>

<template>
  <div class="relative cursor-pointer pl-3"
       @click="collapsible && (collapsed = !collapsed)">
    <!-- Sidebar rail -->
    <div class="absolute left-0 top-1 bottom-0 w-px"
         :style="{ background: railColor, opacity: 0.55 }" />

    <!-- Pill heading (sticky below nav bar). Explicit opaque bg so scrolled
         content beneath the pill doesn't bleed through. --bg-elev-1 matches
         the kanban column surface (flush) and reads as a subtle header rail
         on canvas-level surfaces like PlanView. -->
    <div
      class="flex items-center gap-2 select-none sticky z-10 py-0.5 bg-[--bg-elev-1]"
      :class="[collapsed ? '' : 'mb-1']"
      :style="{ top: stickyTop }">
      <span class="text-xs font-medium uppercase tracking-wide"
            :style="color ? { color } : {}"
            :class="color ? '' : 'text-[--fg-3]'"
            @click.stop="emit('header-click')">
        {{ label }}
      </span>
      <span v-if="collapsible" class="text-[--fg-5] text-xs transition-transform"
            :class="collapsed ? '' : 'rotate-90'">▸</span>
      <slot name="header-right" />
    </div>
    <!-- Content -->
    <div v-show="!collapsed" @click.stop>
      <slot />
    </div>
  </div>
</template>
