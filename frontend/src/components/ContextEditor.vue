<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useContextStore } from '../stores/context'

const store = useContextStore()
const editing = ref<string | null>(null)
const editBody = ref('')
const newSubject = ref('')

function startEdit(subject: string, body: string) {
  editing.value = subject; editBody.value = body
}

async function saveEdit() {
  if (!editing.value) return
  await store.saveEntry(editing.value, editBody.value)
  editing.value = null
}

async function addEntry() {
  if (!newSubject.value.trim()) return
  await store.saveEntry(newSubject.value.trim(), '')
  newSubject.value = ''
}

onMounted(() => store.fetchEntries())
</script>

<template>
  <div class="space-y-3">
    <div v-for="entry in store.entries" :key="entry.subject"
         class="bg-white/5 border border-white/10 rounded-xl p-4">
      <div class="flex justify-between items-center mb-2">
        <h3 class="font-semibold text-sm">{{ entry.subject }}</h3>
        <div class="flex gap-2">
          <button @click="startEdit(entry.subject, entry.body)"
                  class="text-xs text-white/50 hover:text-white">Edit</button>
          <button @click="store.deleteEntry(entry.subject)"
                  class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
        </div>
      </div>
      <div v-if="editing === entry.subject">
        <textarea v-model="editBody" rows="4"
                  class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
        <div class="flex gap-2 mt-2">
          <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
          <button @click="editing = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
        </div>
      </div>
      <p v-else class="text-xs text-white/50 line-clamp-2">{{ entry.body || '(empty)' }}</p>
    </div>

    <div class="flex gap-2 mt-4">
      <input v-model="newSubject" placeholder="New subject..."
             class="flex-1 bg-white/5 border border-white/20 rounded px-3 py-2 text-sm outline-none focus:border-white/50" />
      <button @click="addEntry" class="bg-white/10 hover:bg-white/20 px-4 py-2 rounded text-sm">Add</button>
    </div>
  </div>
</template>
