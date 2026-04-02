<script setup lang="ts">
import { ref, watch } from 'vue'

export interface SearchResult {
  id: string
  label: string
  sublabel?: string
}

const props = defineProps<{
  searchFn: (query: string) => Promise<SearchResult[]>
  placeholder?: string
}>()

const emit = defineEmits<{
  (e: 'select', item: SearchResult): void
}>()

const query = ref('')
const results = ref<SearchResult[]>([])
const open = ref(false)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(query, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!val.trim()) {
    results.value = []
    open.value = false
    return
  }
  debounceTimer = setTimeout(async () => {
    results.value = await props.searchFn(val)
    open.value = results.value.length > 0
  }, 300)
})

function select(item: SearchResult) {
  emit('select', item)
  query.value = ''
  results.value = []
  open.value = false
}

function onBlur() {
  // Delay close so click can fire first
  setTimeout(() => { open.value = false }, 150)
}
</script>

<template>
  <div class="relative">
    <input
      v-model="query"
      :placeholder="placeholder ?? 'Search...'"
      @focus="open = results.length > 0"
      @blur="onBlur"
      class="w-full bg-gray-800 text-sm text-white rounded px-2 py-1 border border-white/10 outline-none focus:border-white/30" />
    <ul
      v-if="open && results.length"
      class="absolute z-50 top-full left-0 right-0 mt-1 bg-gray-800 border border-white/20 rounded shadow-xl max-h-48 overflow-y-auto">
      <li
        v-for="item in results" :key="item.id"
        @mousedown.prevent="select(item)"
        class="flex flex-col px-3 py-2 cursor-pointer hover:bg-white/10 transition-colors">
        <span class="text-sm text-white/90">{{ item.label }}</span>
        <span v-if="item.sublabel" class="text-xs text-white/40">{{ item.sublabel }}</span>
      </li>
    </ul>
  </div>
</template>
