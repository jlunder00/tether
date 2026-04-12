<script setup lang="ts">
import { ref } from 'vue'

withDefaults(defineProps<{
  label: string
  color?: string
  collapsible?: boolean
  level?: number  // 0 = top-level (anchor/context), 1 = nested (milestone)
}>(), {
  collapsible: true,
  level: 0,
})

const collapsed = ref(false)
</script>

<template>
  <div :class="[
    'rounded-lg transition-all',
    level === 0 ? 'bg-white/5 border border-white/10 p-3' : 'bg-white/[0.03] border border-white/[0.06] p-2 ml-1',
  ]">
    <!-- Pill heading -->
    <div
      class="flex items-center gap-2 cursor-pointer select-none"
      :class="collapsed ? '' : 'mb-2'"
      @click="collapsible && (collapsed = !collapsed)">
      <span v-if="color" class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: color }" />
      <span class="text-xs font-medium uppercase tracking-wide px-2 py-0.5 rounded-full"
            :style="color ? { backgroundColor: color + '22', color } : {}"
            :class="color ? '' : 'text-white/50 bg-white/10'">
        {{ label }}
      </span>
      <span v-if="collapsible" class="text-white/30 text-xs transition-transform"
            :class="collapsed ? '' : 'rotate-90'">▸</span>
      <slot name="header-right" />
    </div>
    <!-- Content -->
    <div v-show="!collapsed">
      <slot />
    </div>
  </div>
</template>
