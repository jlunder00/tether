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

// Opaque background colors — mix color with base dark bg to prevent bleed-through
// Base dark bg is approximately rgb(17, 24, 39) — gray-900
function mixWithDark(hex: string, alpha: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const base = { r: 17, g: 24, b: 39 }
  const mr = Math.round(base.r * (1 - alpha) + r * alpha)
  const mg = Math.round(base.g * (1 - alpha) + g * alpha)
  const mb = Math.round(base.b * (1 - alpha) + b * alpha)
  return `rgb(${mr},${mg},${mb})`
}

const containerBg = computed(() => {
  if (props.color) return mixWithDark(props.color, 0.08)
  return props.level === 0 ? 'rgb(20,27,42)' : 'rgb(17,24,39)'
})

const headerBg = computed(() => {
  if (props.color) return mixWithDark(props.color, 0.12)
  return props.level === 0 ? 'rgb(22,29,44)' : 'rgb(17,24,39)'
})

const stickyTop = computed(() => {
  if (props.level === 0) return `${props.stickyOffset}px`
  return `${props.stickyOffset + 28}px`
})
</script>

<template>
  <div :class="[
    'rounded-lg transition-all cursor-pointer',
    level === 0 ? 'border border-white/10 p-3' : 'border border-white/[0.06] p-2 ml-1',
  ]"
  :style="{ backgroundColor: containerBg }"
  @click="collapsible && (collapsed = !collapsed)">
    <!-- Pill heading (sticky below nav bar) -->
    <div
      class="flex items-center gap-2 select-none sticky z-10 rounded py-0.5"
      :class="[collapsed ? '' : 'mb-2']"
      :style="{ backgroundColor: headerBg, top: stickyTop }">
      <span class="text-xs font-medium uppercase tracking-wide px-2 py-0.5 rounded-full"
            :style="color ? { backgroundColor: color + '22', color } : {}"
            :class="color ? '' : 'text-white/50 bg-white/10'"
            @click.stop="emit('header-click')">
        {{ label }}
      </span>
      <span v-if="collapsible" class="text-white/30 text-xs transition-transform"
            :class="collapsed ? '' : 'rotate-90'">▸</span>
      <slot name="header-right" />
    </div>
    <!-- Content -->
    <div v-show="!collapsed" @click.stop>
      <slot />
    </div>
  </div>
</template>
