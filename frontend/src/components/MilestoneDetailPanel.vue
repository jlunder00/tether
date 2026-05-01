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
  pending: 'bg-[--bg-elev-2]',
  in_progress: 'bg-[--status-doing-fg]',
  done: 'bg-[--status-done-fg]',
  skipped: 'bg-orange-400',
  blocked: 'bg-[--status-block-fg]',
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
  <div class="p-5 flex flex-col gap-5 text-[--fg-1] min-h-full">

      <!-- Header context info (close button is in SlideOverStack) -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span v-if="milestone" class="text-xs px-2 py-0.5 rounded-full bg-[--bg-elev-2] text-[--fg-3]">
            {{ milestone.context_subject }}
          </span>
        </div>
      </div>

      <!-- Not found -->
      <div v-if="!milestone" class="text-[--fg-4] text-sm">Milestone not found.</div>

      <template v-else>

        <!-- Title -->
        <input
          :value="milestone.name"
          @change="onNameChange"
          class="bg-transparent text-xl font-semibold outline-none border-b border-[--border-1] focus:border-[--fg-3] pb-1 w-full"
          placeholder="Milestone name" />

        <!-- Status + override -->
        <div class="flex items-center gap-3 flex-wrap">
          <div class="flex items-center gap-2">
            <label class="text-xs text-[--fg-3] uppercase tracking-wide">Status</label>
            <span :class="STATUS_COLORS[milestone.status] ?? 'bg-[--bg-elev-2]'" class="w-2 h-2 rounded-full flex-shrink-0" />
            <span class="text-sm text-[--fg-2]">{{ milestone.status }}</span>
          </div>
          <div class="flex items-center gap-2">
            <label class="text-xs text-[--fg-3] uppercase tracking-wide">Override</label>
            <select
              :value="milestone.status_override ? milestone.status : ''"
              @change="onStatusChange"
              class="bg-[--bg-elev-1] text-[--fg-1] text-sm rounded px-2 py-1 border border-[--border-1] outline-none">
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
          <label class="text-xs text-[--fg-3] uppercase tracking-wide">Target date</label>
          <input
            type="date"
            :value="milestone.target_date ?? ''"
            @change="onTargetDateChange"
            class="bg-[--bg-elev-1] text-[--fg-1] text-sm rounded px-2 py-1 border border-[--border-1] outline-none" />
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
          <label class="text-xs text-[--fg-3] uppercase tracking-wide">Description</label>
          <textarea
            :value="milestone.description ?? ''"
            @blur="onDescBlur"
            rows="3"
            placeholder="Add a description..."
            class="bg-[--bg-elev-1] text-sm text-[--fg-2] rounded px-3 py-2 border border-[--border-soft] outline-none focus:border-[--border-1] resize-none" />
        </div>

        <!-- Progress -->
        <div class="flex flex-col gap-1">
          <div class="flex items-center justify-between text-xs text-[--fg-3]">
            <span class="uppercase tracking-wide">Progress</span>
            <span>{{ milestone.done_count }}/{{ milestone.task_count }} tasks done</span>
          </div>
          <div class="w-full h-1.5 rounded-full bg-[--bg-elev-2] overflow-hidden">
            <div class="h-full bg-[--status-done-fg] transition-all" :style="{ width: progressPct + '%' }" />
          </div>
        </div>

        <!-- Linked tasks -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-[--fg-3] uppercase tracking-wide">Tasks</span>
          <div v-if="!milestone.tasks.length" class="text-xs text-[--fg-6] italic">No tasks linked</div>
          <button
            v-for="t in milestone.tasks" :key="t.id"
            @click="openTask(t.id)"
            class="flex items-center gap-2 text-left group">
            <span :class="STATUS_COLORS[t.status] ?? 'bg-[--bg-elev-2]'" class="w-2 h-2 rounded-full flex-shrink-0" />
            <span class="text-sm text-[--fg-2] hover:text-[--fg-1] flex-1 truncate">{{ t.text ?? t.id }}</span>
            <span v-if="t.plan_date" class="text-xs text-[--fg-5] flex-shrink-0">{{ t.plan_date }}</span>
          </button>
        </div>

        <!-- Links -->
        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <span class="text-xs text-[--fg-3] uppercase tracking-wide">Links</span>
            <button @click="showAddLink = !showAddLink" class="text-xs text-[--fg-4] hover:text-[--fg-2]">+ Add link</button>
          </div>
          <ul class="flex flex-col gap-1">
            <li v-for="l in links" :key="l.id" class="flex items-center gap-2 group">
              <span class="flex-shrink-0">{{ LINK_ICONS[l.category] ?? '📎' }}</span>
              <a :href="l.url" target="_blank" class="flex-1 text-sm text-blue-300 hover:text-blue-200 truncate">
                {{ l.label || l.url }}
              </a>
              <span class="text-xs px-1 py-0.5 rounded bg-[--bg-elev-2] text-[--fg-4] flex-shrink-0">{{ l.category }}</span>
              <button
                @click="removeLink(l.id)"
                class="text-[--fg-6] hover:text-[--status-block-fg] text-xs opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">✕</button>
            </li>
          </ul>
          <div v-if="showAddLink" class="flex flex-col gap-2 bg-[--bg-elev-1] rounded p-3 border border-[--border-soft]">
            <input v-model="newLinkUrl" placeholder="URL" class="bg-[--bg-elev-2] text-sm text-[--fg-1] rounded px-2 py-1 outline-none border border-[--border-soft] focus:border-[--border-1]" />
            <input v-model="newLinkLabel" placeholder="Label (optional)" class="bg-[--bg-elev-2] text-sm text-[--fg-1] rounded px-2 py-1 outline-none border border-[--border-soft] focus:border-[--border-1]" />
            <select v-model="newLinkCategory" class="bg-[--bg-elev-2] text-sm text-[--fg-1] rounded px-2 py-1 outline-none border border-[--border-soft]">
              <option value="document">Document</option>
              <option value="meeting">Meeting</option>
              <option value="pr">PR</option>
              <option value="issue">Issue</option>
              <option value="other">Other</option>
            </select>
            <div class="flex gap-2 justify-end">
              <button @click="showAddLink = false" class="text-xs text-[--fg-4] hover:text-[--fg-2]">Cancel</button>
              <button @click="addLink" class="text-xs text-[--fg-3] hover:text-[--fg-1] px-2 py-1 rounded bg-[--bg-elev-2]">Add</button>
            </div>
          </div>
        </div>

        <!-- Dependencies -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-[--fg-3] uppercase tracking-wide">Dependencies</span>

          <div class="flex flex-col gap-1">
            <span class="text-xs text-[--fg-4]">Blocked by</span>
            <div v-if="!deps.blocked_by.length" class="text-xs text-[--fg-6] italic">None</div>
            <button
              v-for="d in deps.blocked_by" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span class="w-2 h-2 rounded-full bg-[--bg-elev-2] flex-shrink-0" />
              <span class="text-sm text-[--fg-2] hover:text-[--fg-1] flex-1 truncate">{{ d.name || d.entity_id }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-[--bg-elev-2] text-[--fg-4]">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-[--fg-6] hover:text-[--status-block-fg] text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <div class="flex flex-col gap-1">
            <span class="text-xs text-[--fg-4]">Blocks</span>
            <div v-if="!deps.blocks.length" class="text-xs text-[--fg-6] italic">None</div>
            <button
              v-for="d in deps.blocks" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span class="w-2 h-2 rounded-full bg-[--bg-elev-2] flex-shrink-0" />
              <span class="text-sm text-[--fg-2] hover:text-[--fg-1] flex-1 truncate">{{ d.name || d.entity_id }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-[--bg-elev-2] text-[--fg-4]">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-[--fg-6] hover:text-[--status-block-fg] text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <SearchAutocomplete :search-fn="searchForDependency" placeholder="Search tasks/milestones..." @select="addDependencyFromSearch" />
        </div>

        <!-- Delete -->
        <div class="mt-auto pt-4 border-t border-[--border-soft]">
          <button @click="deleteMilestone" class="text-[--status-block-fg] hover:opacity-80 text-sm">Delete milestone</button>
        </div>

      </template>
  </div>
</template>
