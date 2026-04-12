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

const emit = defineEmits<{ (e: 'header-click'): void }>()

const collapsed = ref(false)
</script>

<template>
  <div :class="[
    'rounded-lg transition-all cursor-pointer',
    level === 0 ? 'bg-white/5 border border-white/10 p-3' : 'bg-white/[0.03] border border-white/[0.06] p-2 ml-1',
  ]"
  :style="color ? { backgroundColor: color + '15' } : {}"
  @click="collapsible && (collapsed = !collapsed)">
    <!-- Pill heading (sticky within scroll containers) -->
    <div
      class="flex items-center gap-2 select-none sticky top-0 z-10 backdrop-blur-sm"
      :class="[collapsed ? '' : 'mb-2', level === 0 ? 'bg-white/5' : 'bg-gray-900/80']"
      :style="{ top: level === 1 ? '28px' : '0px' }">
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
