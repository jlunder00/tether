<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../lib/api'
import SearchAutocomplete from './SearchAutocomplete.vue'
import type { SearchResult } from './SearchAutocomplete.vue'
import MotifPicker, { type MotifSlot } from './MotifPicker.vue'
import { useMilestoneStore } from '../stores/milestones'
import { usePlanStore } from '../stores/plan'
import { useLinks } from '../composables/useLinks'
import { useDependencies } from '../composables/useDependencies'
import { useSlideOver } from '../composables/useSlideOver'

const props = defineProps<{ milestoneId: string }>()
const { push: pushPanel, pop: popPanel } = useSlideOver()
const milestoneStore = useMilestoneStore()
const planStore = usePlanStore()

const milestone = computed(() => milestoneStore.all.find(m => m.id === props.milestoneId) ?? null)

const { links, create: createLink, remove: removeLink } = useLinks(() => 'milestones', () => props.milestoneId)
const { deps, add: addDep, remove: removeDep } = useDependencies(() => 'milestone', () => props.milestoneId)

async function searchForDependency(q: string): Promise<SearchResult[]> {
  const resp = await api(`/api/search?q=${encodeURIComponent(q)}&type=all`)
  if (!resp.ok) return []
  const items = await resp.json()
  return items.filter((i: SearchResult) => i.id !== props.milestoneId)
}

async function addDependencyFromSearch(item: SearchResult) {
  await addDep(item.type ?? 'task', item.id, 'milestone', props.milestoneId)
}

// Links UI
const showAddLink = ref(false)
const newLinkUrl = ref('')
const newLinkLabel = ref('')
const newLinkCategory = ref('other')

const LINK_ICONS: Record<string, string> = {
  document: '📄',
  meeting: '🔗',
  pr: '⚡',
  issue: '🐛',
  other: '📎',
}

async function addLink() {
  const url = newLinkUrl.value.trim()
  if (!url) return
  await createLink(url, newLinkLabel.value.trim() || null, newLinkCategory.value)
  newLinkUrl.value = ''
  newLinkLabel.value = ''
  newLinkCategory.value = 'other'
  showAddLink.value = false
}

// Patch milestone
async function patchMilestone(fields: Record<string, unknown>) {
  if (!milestone.value) return
  await milestoneStore.patchMilestone(props.milestoneId, fields as Parameters<typeof milestoneStore.patchMilestone>[1])
}

function onNameChange(e: Event) {
  patchMilestone({ name: (e.target as HTMLInputElement).value })
}

function onDescBlur(e: Event) {
  patchMilestone({ description: (e.target as HTMLTextAreaElement).value || null })
}

function onTargetDateChange(e: Event) {
  patchMilestone({ target_date: (e.target as HTMLInputElement).value || null })
}

function onStatusChange(e: Event) {
  patchMilestone({ status: (e.target as HTMLSelectElement).value })
}

// Progress bar
const progressPct = computed(() => {
  const m = milestone.value
  if (!m || m.task_count === 0) return 0
  return Math.round((m.done_count / m.task_count) * 100)
})

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-white/20',
  in_progress: 'bg-blue-400',
  done: 'bg-green-400',
  skipped: 'bg-orange-400',
  blocked: 'bg-red-400',
}

function openTask(taskId: string) {
  pushPanel({ kind: 'task', entityId: taskId })
}

function openDep(type: string, id: string) {
  if (type === 'task') {
    pushPanel({ kind: 'task', entityId: id })
  } else {
    pushPanel({ kind: 'milestone', entityId: id })
  }
}

async function deleteMilestone() {
  if (!confirm('Delete this milestone?')) return
  await milestoneStore.deleteMilestone(props.milestoneId)
  popPanel()
}

onMounted(async () => {
  if (!milestoneStore.all.length) await milestoneStore.fetchAll()
  if (!planStore.plan) await planStore.fetchPlan()
})
</script>

<template>
  <div class="p-5 flex flex-col gap-5 text-white min-h-full">

      <!-- Header context info (close button is in SlideOverStack) -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span v-if="milestone" class="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/60">
            {{ milestone.context_subject }}
          </span>
        </div>
      </div>

      <!-- Not found -->
      <div v-if="!milestone" class="text-white/40 text-sm">Milestone not found.</div>

      <template v-else>

        <!-- Title -->
        <input
          :value="milestone.name"
          @change="onNameChange"
          class="bg-transparent text-xl font-semibold outline-none border-b border-white/20 focus:border-white/50 pb-1 w-full"
          placeholder="Milestone name" />

        <!-- Status + override -->
        <div class="flex items-center gap-3 flex-wrap">
          <div class="flex items-center gap-2">
            <label class="text-xs text-white/50 uppercase tracking-wide">Status</label>
            <span :class="STATUS_COLORS[milestone.status] ?? 'bg-white/20'" class="w-2 h-2 rounded-full flex-shrink-0" />
            <span class="text-sm text-white/70">{{ milestone.status }}</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="text-xs text-white/50 uppercase tracking-wide">Override</label>
            <select
              :value="milestone.status_override ? milestone.status : ''"
              @change="onStatusChange"
              class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none">
              <option value="">Derived</option>
              <option value="pending">Pending</option>
              <option value="in_progress">In Progress</option>
              <option value="done">Done</option>
              <option value="blocked">Blocked</option>
            </select>
          </div>
        </div>

        <!-- Target date -->
        <div class="flex items-center gap-3">
          <label class="text-xs text-white/50 uppercase tracking-wide">Target date</label>
          <input
            type="date"
            :value="milestone.target_date ?? ''"
            @change="onTargetDateChange"
            class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none" />
        </div>

        <!-- Motif -->
        <div data-testid="milestone-motif-picker" class="flex items-center gap-3">
          <MotifPicker
            :model-value="(milestone.motif as MotifSlot | null | undefined) ?? null"
            @update:model-value="(slot) => patchMilestone({ motif: slot })"
          />
        </div>

        <!-- Description -->
        <div class="flex flex-col gap-1">
          <label class="text-xs text-white/50 uppercase tracking-wide">Description</label>
          <textarea
            :value="milestone.description ?? ''"
            @blur="onDescBlur"
            rows="3"
            placeholder="Add a description..."
            class="bg-gray-800 text-sm text-white/80 rounded px-3 py-2 border border-white/10 outline-none focus:border-white/30 resize-none" />
        </div>

        <!-- Progress -->
        <div class="flex flex-col gap-1">
          <div class="flex items-center justify-between text-xs text-white/50">
            <span class="uppercase tracking-wide">Progress</span>
            <span>{{ milestone.done_count }}/{{ milestone.task_count }} tasks done</span>
          </div>
          <div class="w-full h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div class="h-full bg-green-400 transition-all" :style="{ width: progressPct + '%' }" />
          </div>
        </div>

        <!-- Linked tasks -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-white/50 uppercase tracking-wide">Tasks</span>
          <div v-if="!milestone.tasks.length" class="text-xs text-white/20 italic">No tasks linked</div>
          <button
            v-for="t in milestone.tasks" :key="t.id"
            @click="openTask(t.id)"
            class="flex items-center gap-2 text-left group">
            <span :class="STATUS_COLORS[t.status] ?? 'bg-white/20'" class="w-2 h-2 rounded-full flex-shrink-0" />
            <span class="text-sm text-white/70 hover:text-white flex-1 truncate">{{ t.text ?? t.id }}</span>
            <span v-if="t.plan_date" class="text-xs text-white/30 flex-shrink-0">{{ t.plan_date }}</span>
          </button>
        </div>

        <!-- Links -->
        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <span class="text-xs text-white/50 uppercase tracking-wide">Links</span>
            <button @click="showAddLink = !showAddLink" class="text-xs text-white/40 hover:text-white/70">+ Add link</button>
          </div>
          <ul class="flex flex-col gap-1">
            <li v-for="l in links" :key="l.id" class="flex items-center gap-2 group">
              <span class="flex-shrink-0">{{ LINK_ICONS[l.category] ?? '📎' }}</span>
              <a :href="l.url" target="_blank" class="flex-1 text-sm text-blue-300 hover:text-blue-200 truncate">
                {{ l.label || l.url }}
              </a>
              <span class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/40 flex-shrink-0">{{ l.category }}</span>
              <button
                @click="removeLink(l.id)"
                class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">✕</button>
            </li>
          </ul>
          <div v-if="showAddLink" class="flex flex-col gap-2 bg-gray-800 rounded p-3 border border-white/10">
            <input v-model="newLinkUrl" placeholder="URL" class="bg-gray-700 text-sm text-white rounded px-2 py-1 outline-none border border-white/10 focus:border-white/30" />
            <input v-model="newLinkLabel" placeholder="Label (optional)" class="bg-gray-700 text-sm text-white rounded px-2 py-1 outline-none border border-white/10 focus:border-white/30" />
            <select v-model="newLinkCategory" class="bg-gray-700 text-sm text-white rounded px-2 py-1 outline-none border border-white/10">
              <option value="document">Document</option>
              <option value="meeting">Meeting</option>
              <option value="pr">PR</option>
              <option value="issue">Issue</option>
              <option value="other">Other</option>
            </select>
            <div class="flex gap-2 justify-end">
              <button @click="showAddLink = false" class="text-xs text-white/40 hover:text-white/70">Cancel</button>
              <button @click="addLink" class="text-xs text-white/60 hover:text-white px-2 py-1 rounded bg-white/10">Add</button>
            </div>
          </div>
        </div>

        <!-- Dependencies -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-white/50 uppercase tracking-wide">Dependencies</span>

          <div class="flex flex-col gap-1">
            <span class="text-xs text-white/40">Blocked by</span>
            <div v-if="!deps.blocked_by.length" class="text-xs text-white/20 italic">None</div>
            <button
              v-for="d in deps.blocked_by" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span class="w-2 h-2 rounded-full bg-white/20 flex-shrink-0" />
              <span class="text-sm text-white/70 hover:text-white flex-1 truncate">{{ d.name || d.entity_id }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/40">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <div class="flex flex-col gap-1">
            <span class="text-xs text-white/40">Blocks</span>
            <div v-if="!deps.blocks.length" class="text-xs text-white/20 italic">None</div>
            <button
              v-for="d in deps.blocks" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span class="w-2 h-2 rounded-full bg-white/20 flex-shrink-0" />
              <span class="text-sm text-white/70 hover:text-white flex-1 truncate">{{ d.name || d.entity_id }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/40">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <SearchAutocomplete :search-fn="searchForDependency" placeholder="Search tasks/milestones..." @select="addDependencyFromSearch" />
        </div>

        <!-- Delete -->
        <div class="mt-auto pt-4 border-t border-white/10">
          <button @click="deleteMilestone" class="text-red-400 hover:text-red-300 text-sm">Delete milestone</button>
        </div>

      </template>
  </div>
</template>
