<script setup lang="ts">
import { onMounted, onUnmounted, watch } from 'vue'
import { useTheme } from '../composables/useTheme'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()

const { THEMES, activeTheme, activeMode, isThemeUnlocked, applyTheme, previewTheme, setMode } = useTheme()

function close() {
  emit('update:modelValue', false)
}

function onPreview(themeId: string) {
  previewTheme(themeId)
}

function onRestore() {
  previewTheme(activeTheme.value)
}

function onSelect(themeId: string) {
  const theme = THEMES.find(t => t.id === themeId)
  if (!theme) return
  previewTheme(themeId)
  if (isThemeUnlocked(theme)) applyTheme(themeId)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.modelValue) close()
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))

watch(() => props.modelValue, (open) => {
  if (!open) onRestore()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="modelValue"
        data-testid="theme-drawer-backdrop"
        class="fixed inset-0 z-40 bg-black/40"
        @click="close"
      />
    </Transition>

    <Transition name="slide-over">
      <aside
        v-if="modelValue"
        data-testid="theme-drawer"
        role="dialog"
        aria-label="Theme picker"
        class="fixed top-0 right-0 z-50 h-full w-full sm:w-[420px] bg-gray-900 border-l border-white/10 shadow-2xl overflow-y-auto"
      >
        <div class="flex items-center gap-2 px-4 py-3 border-b border-white/10">
          <span class="text-sm font-semibold text-white/80">Theme</span>
          <div class="flex-1" />
          <button
            data-testid="theme-drawer-close"
            class="text-white/30 hover:text-white transition-colors p-1 rounded hover:bg-white/10"
            title="Close (Esc)"
            aria-label="Close"
            @click="close"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="p-4 space-y-4">
          <!-- Day/night mode toggle -->
          <div class="flex items-center justify-between rounded-lg bg-gray-800 px-3 py-2.5">
            <span class="text-xs uppercase tracking-wider text-white/50">Mode</span>
            <div class="flex items-center gap-1" role="group" aria-label="Mode">
              <button
                data-testid="mode-light"
                class="px-2.5 py-1 rounded text-xs transition-colors"
                :class="activeMode === 'light' ? 'bg-white/20 text-white' : 'text-white/50 hover:bg-white/10'"
                :aria-pressed="activeMode === 'light'"
                @click="setMode('light')"
              >Day</button>
              <button
                data-testid="mode-dark"
                class="px-2.5 py-1 rounded text-xs transition-colors"
                :class="activeMode === 'dark' ? 'bg-white/20 text-white' : 'text-white/50 hover:bg-white/10'"
                :aria-pressed="activeMode === 'dark'"
                @click="setMode('dark')"
              >Night</button>
            </div>
          </div>

          <!-- Theme swatch grid -->
          <p class="text-xs text-white/40">Hover to preview, click to apply. Paid themes preview only until unlocked.</p>
          <div class="grid grid-cols-2 gap-2">
            <button
              v-for="theme in THEMES"
              :key="theme.id"
              data-testid="theme-swatch"
              :data-theme-id="theme.id"
              @click="onSelect(theme.id)"
              @mouseenter="onPreview(theme.id)"
              @mouseleave="onRestore"
              :title="theme.name"
              :aria-pressed="activeTheme === theme.id"
              class="relative flex flex-col items-start gap-1.5 rounded-lg p-2.5 border transition-all text-left"
              :class="[
                activeTheme === theme.id
                  ? 'border-indigo-500 ring-1 ring-indigo-500'
                  : 'border-gray-700 hover:border-gray-500',
              ]"
            >
              <span
                class="w-full h-6 rounded"
                :style="{ background: `linear-gradient(135deg, ${theme.canvas} 60%, ${theme.accent} 100%)` }"
              />
              <span class="text-xs text-white/80 font-medium leading-tight">{{ theme.name }}</span>
              <span
                v-if="theme.tier !== 'free'"
                class="absolute top-1.5 right-1.5 text-[9px] font-bold uppercase tracking-wide px-1 py-0.5 rounded"
                :class="isThemeUnlocked(theme) ? 'bg-emerald-700/70 text-emerald-200' : 'bg-gray-700/80 text-white/40'"
              >{{ isThemeUnlocked(theme) ? 'oss' : 'paid' }}</span>
            </button>
          </div>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.slide-over-enter-active, .slide-over-leave-active {
  transition: transform 0.15s ease, opacity 0.15s ease;
}
.slide-over-enter-from, .slide-over-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
</style>
