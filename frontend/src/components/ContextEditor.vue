<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useContextStore } from '../stores/context'
import MilestoneDetail from './MilestoneDetail.vue'
import { useMilestoneStore } from '../stores/milestones'

const store = useContextStore()
const editing = ref<string | null>(null)
const editBody = ref('')
const renaming = ref<string | null>(null)
const renameValue = ref('')
const newSubject = ref('')
const expandedGroups = ref<Set<string>>(new Set())

const milestoneStore = useMilestoneStore()
const expandedMilestones = ref<Set<string>>(new Set())
const addingMilestoneFor = ref<string | null>(null)
const newMilestoneName = ref('')

function toggleMilestone(id: string) {
  const next = new Set(expandedMilestones.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  expandedMilestones.value = next
}

async function addMilestone(subject: string) {
  if (!newMilestoneName.value.trim()) return
  await milestoneStore.createMilestone(subject, newMilestoneName.value.trim())
  newMilestoneName.value = ''
  addingMilestoneFor.value = null
}

const topLevel = computed(() =>
  store.entries.filter(e => !e.subject.includes('/'))
)

function childrenOf(subject: string) {
  return store.entries.filter(e =>
    e.subject.startsWith(subject + '/') &&
    e.subject.slice(subject.length + 1).indexOf('/') === -1
  )
}

function toggle(subject: string) {
  if (expandedGroups.value.has(subject)) {
    expandedGroups.value.delete(subject)
  } else {
    expandedGroups.value.add(subject)
  }
}

function startEdit(subject: string, body: string) {
  editing.value = subject
  editBody.value = body
}

async function saveEdit() {
  if (!editing.value) return
  await store.saveEntry(editing.value, editBody.value)
  editing.value = null
}

function startRename(subject: string) {
  renaming.value = subject
  renameValue.value = subject
}

async function saveRename() {
  if (!renaming.value || renameValue.value.trim() === renaming.value) {
    renaming.value = null
    return
  }
  await store.renameEntry(renaming.value, renameValue.value.trim())
  renaming.value = null
}

async function addEntry() {
  if (!newSubject.value.trim()) return
  await store.saveEntry(newSubject.value.trim(), '')
  newSubject.value = ''
}

function prefillSubEntry(parent: string) {
  newSubject.value = parent + '/'
}

function deleteWithConfirm(subject: string, childCount: number) {
  const msg = childCount > 0
    ? `Delete "${subject}" and ${childCount} sub-entr${childCount === 1 ? 'y' : 'ies'}?`
    : `Delete "${subject}"?`
  if (confirm(msg)) store.deleteEntry(subject)
}

onMounted(() => {
  store.fetchEntries()
  milestoneStore.fetchAll()
})
</script>

<template>
  <div class="min-h-screen bg-gray-900 text-white p-6">
  <div class="space-y-3">
    <template v-for="entry in topLevel" :key="entry.subject">
      <!-- Top-level entry -->
      <div class="bg-white/5 border border-white/10 rounded-xl p-4">
        <div class="flex justify-between items-center mb-2">
          <div class="flex items-center gap-2 flex-1 min-w-0">
            <button v-if="childrenOf(entry.subject).length > 0"
                    @click="toggle(entry.subject)"
                    class="text-white/40 hover:text-white/80 text-xs w-4 shrink-0">
              {{ expandedGroups.has(entry.subject) ? '▼' : '▶' }}
            </button>
            <span v-else class="w-4 shrink-0" />

            <template v-if="renaming === entry.subject">
              <input v-model="renameValue" @keyup.enter="saveRename" @keyup.escape="renaming = null"
                     class="flex-1 bg-transparent border-b border-white/40 text-sm outline-none" />
              <span v-if="childrenOf(entry.subject).length > 0"
                    class="text-xs text-yellow-400/70 ml-1">
                (renames {{ childrenOf(entry.subject).length }} sub-entr{{ childrenOf(entry.subject).length === 1 ? 'y' : 'ies' }})
              </span>
            </template>
            <h3 v-else class="font-semibold text-sm truncate">{{ entry.subject }}</h3>
          </div>

          <div class="flex gap-2 shrink-0">
            <button @click="startEdit(entry.subject, entry.body)"
                    class="text-xs text-white/50 hover:text-white">Edit</button>
            <template v-if="renaming === entry.subject">
              <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
              <button @click="renaming = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
            </template>
            <button v-else @click="startRename(entry.subject)"
                    class="text-xs text-white/50 hover:text-white">Rename</button>
            <button @click="deleteWithConfirm(entry.subject, childrenOf(entry.subject).length)"
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

        <!-- Milestone chips -->
        <div v-if="milestoneStore.bySubject[entry.subject]?.length" class="mt-2 flex flex-wrap gap-1">
          <button
            v-for="m in milestoneStore.bySubject[entry.subject]" :key="m.id"
            @click="toggleMilestone(m.id)"
            :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
            class="text-xs px-1.5 py-0.5 rounded border flex items-center gap-1"
            :class="m.color ? 'hover:opacity-80' : 'bg-white/10 hover:bg-white/20 border-transparent'">
            <span :class="m.status === 'done' ? 'bg-green-400'
                        : m.status === 'in_progress' ? 'bg-blue-400'
                        : m.status === 'blocked' ? 'bg-red-400' : 'bg-white/20'"
                  class="w-1.5 h-1.5 rounded-full" />
            {{ m.name }} {{ m.done_count }}/{{ m.task_count }}
          </button>
        </div>
        <template v-for="m in milestoneStore.bySubject[entry.subject]" :key="'detail-' + m.id">
          <MilestoneDetail
            v-if="expandedMilestones.has(m.id)"
            :milestone="m"
            @close="toggleMilestone(m.id)" />
        </template>
        <div v-if="addingMilestoneFor === entry.subject" class="mt-2 flex gap-2">
          <input v-model="newMilestoneName" placeholder="Milestone name…"
                 @keydown.enter="addMilestone(entry.subject)"
                 class="flex-1 bg-transparent border-b border-white/30 outline-none text-xs" />
          <button @click="addMilestone(entry.subject)" class="text-xs text-white/60 hover:text-white">Add</button>
          <button @click="addingMilestoneFor = null; newMilestoneName = ''"
                  class="text-xs text-white/40">cancel</button>
        </div>
        <button v-else @click="addingMilestoneFor = entry.subject"
                class="mt-1 text-xs text-white/30 hover:text-white/60">+ milestone</button>

        <!-- Children (expanded) -->
        <template v-if="expandedGroups.has(entry.subject)">
          <div v-for="child in childrenOf(entry.subject)" :key="child.subject"
               class="mt-2 ml-6 bg-white/5 border border-white/10 rounded-lg p-3">
            <div class="flex justify-between items-center mb-1">
              <template v-if="renaming === child.subject">
                <input v-model="renameValue" @keyup.enter="saveRename" @keyup.escape="renaming = null"
                       class="flex-1 bg-transparent border-b border-white/40 text-sm outline-none" />
              </template>
              <h4 v-else class="font-medium text-sm truncate">
                {{ child.subject.split('/').slice(-1)[0] }}
              </h4>
              <div class="flex gap-2 shrink-0">
                <button @click="startEdit(child.subject, child.body)"
                        class="text-xs text-white/50 hover:text-white">Edit</button>
                <template v-if="renaming === child.subject">
                  <button @click="saveRename" class="text-xs text-green-400/70 hover:text-green-400">Save</button>
                  <button @click="renaming = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
                </template>
                <button v-else @click="startRename(child.subject)"
                        class="text-xs text-white/50 hover:text-white">Rename</button>
                <button @click="deleteWithConfirm(child.subject, 0)"
                        class="text-xs text-red-400/60 hover:text-red-400">Delete</button>
              </div>
            </div>
            <div v-if="editing === child.subject">
              <textarea v-model="editBody" rows="3"
                        class="w-full bg-transparent border border-white/20 rounded p-2 text-sm outline-none focus:border-white/50 resize-none" />
              <div class="flex gap-2 mt-2">
                <button @click="saveEdit" class="text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded">Save</button>
                <button @click="editing = null" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
              </div>
            </div>
            <p v-else class="text-xs text-white/50 line-clamp-2">{{ child.body || '(empty)' }}</p>
          </div>

          <!-- Add sub-entry button -->
          <button @click="prefillSubEntry(entry.subject)"
                  class="mt-2 ml-6 text-xs text-white/40 hover:text-white/70">
            + Add sub-entry
          </button>
        </template>
      </div>
    </template>

    <div class="flex gap-2 mt-4">
      <input v-model="newSubject" placeholder="New subject (or Parent/Child)..."
             class="flex-1 bg-white/5 border border-white/20 rounded px-3 py-2 text-sm outline-none focus:border-white/50" />
      <button @click="addEntry" class="bg-white/10 hover:bg-white/20 px-4 py-2 rounded text-sm">Add</button>
    </div>
  </div>
  <router-view />
  </div>
</template>
