<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../lib/api'
import SearchAutocomplete from './SearchAutocomplete.vue'
import type { SearchResult } from './SearchAutocomplete.vue'
import { usePlanStore } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import { useAnchorStore } from '../stores/anchors'
import { useBacklogStore } from '../stores/backlog'
import { useSubtasks } from '../composables/useSubtasks'
import { useLinks } from '../composables/useLinks'
import { useDependencies } from '../composables/useDependencies'
import { useTaskContexts } from '../composables/useTaskContexts'
import { useSlideOver } from '../composables/useSlideOver'
import type { TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'

const props = defineProps<{ taskId: string }>()
const { push: pushPanel, pop: popPanel } = useSlideOver()
const planStore = usePlanStore()
const milestoneStore = useMilestoneStore()
const anchorStore = useAnchorStore()
const backlogStore = useBacklogStore()

// Find the task from the plan OR from the backlog
const taskAndAnchor = computed(() => {
  if (planStore.plan) {
    for (const [aid, anchorPlan] of Object.entries(planStore.plan.anchors)) {
      const t = anchorPlan.tasks.find(t => t.id === props.taskId)
      if (t) return { task: t, anchorId: aid, isBacklog: false }
    }
  }
  const bt = backlogStore.tasks.find(t => t.id === props.taskId)
  if (bt) return { task: bt, anchorId: '', isBacklog: true }
  // Also check standalone fetch
  if (standaloneTask.value) return { task: standaloneTask.value, anchorId: '', isBacklog: true }
  return null
})

const task = computed(() => taskAndAnchor.value?.task ?? null)
const anchorId = computed(() => taskAndAnchor.value?.anchorId ?? '')
const isBacklog = computed(() => taskAndAnchor.value?.isBacklog ?? false)

// Standalone task fetch for when task isn't in plan or backlog store yet
const standaloneTask = ref<any>(null)

// Schedule controls
const scheduleDate = ref(planStore.today)
const scheduleAnchor = ref('')

// Composables
const { subtasks, create: createSubtask, update: updateSubtask, remove: removeSubtask } = useSubtasks(() => props.taskId)
const { links, create: createLink, remove: removeLink } = useLinks(() => 'tasks', () => props.taskId)
const { deps, add: addDep, remove: removeDep } = useDependencies(() => 'task', () => props.taskId)
const { contexts, link: linkContext, unlink: unlinkContext } = useTaskContexts(() => props.taskId)

// Subtasks
const newSubtaskText = ref('')
const subtasksDone = computed(() => subtasks.value.filter(s => s.done).length)

async function addSubtask() {
  const text = newSubtaskText.value.trim()
  if (!text) return
  newSubtaskText.value = ''
  await createSubtask(text)
}

// Links
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

// Task PATCH helper
async function patchTask(fields: Record<string, unknown>) {
  const resp = await api(`/api/tasks/${props.taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  if (isBacklog.value) {
    // Update standalone task from response if applicable
    if (resp.ok && standaloneTask.value) {
      standaloneTask.value = await resp.json()
    }
    await backlogStore.fetchTasks()
  } else {
    await planStore.fetchPlan()
  }
}

// Text editing
function onTextChange(e: Event) {
  const text = (e.target as HTMLInputElement).value
  patchTask({ text })
}

// Status
function onStatusChange(e: Event) {
  const status = (e.target as HTMLSelectElement).value as TaskStatus
  patchTask({ status })
}

// Description
function onDescBlur(e: Event) {
  const description = (e.target as HTMLTextAreaElement).value || null
  patchTask({ description })
}

// Follow-up config
const showFollowup = ref(false)

function toggleFollowup(enabled: boolean) {
  const fc: FollowupConfig = enabled ? {
    enabled: true,
    pre_ack_interval_min: 5,
    pre_ack_max_pings: 3,
    post_ack_interval_min: 15,
    post_ack_pings: 2,
  } : { enabled: false, pre_ack_interval_min: 5, pre_ack_max_pings: 3, post_ack_interval_min: 15, post_ack_pings: 2 }
  patchTask({ followup_config: enabled ? fc : null })
}

function patchFollowup(fields: Partial<FollowupConfig>) {
  if (!task.value?.followup_config) return
  patchTask({ followup_config: { ...task.value.followup_config, ...fields } })
}

// Schedule / Unschedule
async function scheduleTask() {
  if (!scheduleDate.value || !scheduleAnchor.value) return
  await api(`/api/tasks/${props.taskId}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: scheduleDate.value, anchor_id: scheduleAnchor.value }),
  })
  await planStore.fetchPlan(scheduleDate.value)
  await backlogStore.fetchTasks()
  // Panel stays open — the task has moved, stores refreshed above
}

async function moveToBacklog() {
  await api(`/api/tasks/${props.taskId}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date: null, anchor_id: null }),
  })
  await planStore.fetchPlan()
  await backlogStore.fetchTasks()
}

async function moveToAnchor(newAnchorId: string) {
  const date = planStore.plan?.date ?? planStore.today
  await api(`/api/tasks/${props.taskId}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ date, anchor_id: newAnchorId }),
  })
  await planStore.fetchPlan()
}

// Delete
async function deleteTask() {
  if (!confirm('Delete this task?')) return
  await api(`/api/tasks/${props.taskId}`, { method: 'DELETE' })
  popPanel()
  if (isBacklog.value) {
    await backlogStore.fetchTasks()
  } else {
    await planStore.fetchPlan()
  }
}

// Navigate to milestone panel (push onto slide-over stack)
function openMilestone(milestoneId: string) {
  pushPanel({ kind: 'milestone', entityId: milestoneId })
}

// Search functions for dependency and milestone linking
async function searchForDependency(q: string): Promise<SearchResult[]> {
  const resp = await api(`/api/search?q=${encodeURIComponent(q)}&type=all`)
  if (!resp.ok) return []
  const items = await resp.json()
  // Exclude self
  return items.filter((i: SearchResult) => i.id !== props.taskId)
}

async function searchForMilestone(q: string): Promise<SearchResult[]> {
  const resp = await api(`/api/search?q=${encodeURIComponent(q)}&type=milestone`)
  if (!resp.ok) return []
  return resp.json()
}

async function addDependencyFromSearch(item: SearchResult) {
  // This task is blocked by the selected item
  await addDep(item.type ?? 'task', item.id, 'task', props.taskId)
}

async function linkMilestoneFromSearch(item: SearchResult) {
  await api(`/api/milestones/${item.id}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: props.taskId }),
  })
  await milestoneStore.fetchAll()
}

async function searchForContext(q: string): Promise<SearchResult[]> {
  const resp = await api('/api/context')
  if (!resp.ok) return []
  const entries: Array<{ subject: string; body: string }> = await resp.json()
  const lower = q.toLowerCase()
  return entries
    .filter(e => e.subject.toLowerCase().includes(lower))
    .filter(e => !contexts.value.includes(e.subject))
    .map(e => ({ id: e.subject, label: e.subject, type: 'context' }))
}

async function linkContextFromSearch(item: SearchResult) {
  await linkContext(item.id)
}

// Navigate to dependency entity (push onto slide-over stack)
function openDep(type: string, id: string) {
  if (type === 'task') {
    pushPanel({ kind: 'task', entityId: id })
  } else {
    pushPanel({ kind: 'milestone', entityId: id })
  }
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-white/20',
  in_progress: 'bg-blue-400',
  done: 'bg-green-400',
  skipped: 'bg-orange-400',
  blocked: 'bg-red-400',
}

// Resolve dependency entity_id to a display name
function depLabel(type: string, entityId: string): string {
  if (type === 'milestone') {
    const m = milestoneStore.all.find(m => m.id === entityId)
    if (m) return m.name
  } else {
    // Search today's plan tasks
    if (planStore.plan) {
      for (const anchor of Object.values(planStore.plan.anchors)) {
        const t = anchor.tasks.find(t => t.id === entityId)
        if (t) return t.text
      }
    }
    // Search backlog
    const bt = backlogStore.tasks.find(t => t.id === entityId)
    if (bt) return bt.text
  }
  return entityId.slice(0, 8) + '…'
}

onMounted(async () => {
  if (!planStore.plan) await planStore.fetchPlan()
  if (!milestoneStore.all.length) await milestoneStore.fetchAll()
  if (!anchorStore.anchors.length) await anchorStore.fetchAnchors()
  if (!backlogStore.tasks.length) await backlogStore.fetchTasks()
  // If task not found in plan or backlog, fetch it directly
  if (!task.value) {
    try {
      const resp = await api(`/api/tasks/${props.taskId}`)
      if (resp.ok) standaloneTask.value = await resp.json()
    } catch { /* task may not exist */ }
  }
  // Default schedule anchor to first anchor
  if (!scheduleAnchor.value && anchorStore.anchors.length) {
    scheduleAnchor.value = anchorStore.anchors[0].id
  }
})
</script>

<template>
  <div class="p-5 flex flex-col gap-5 text-white min-h-full">

      <!-- Header context info (close button is in SlideOverStack) -->
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-center gap-2 flex-wrap">
          <span v-if="anchorId" class="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/60">
            {{ anchorId }}
          </span>
          <span class="text-xs text-white/40">{{ planStore.activeDate }}</span>
        </div>
      </div>

      <!-- Not found -->
      <div v-if="!task" class="text-white/40 text-sm">Task not found.</div>

      <template v-else>

        <!-- Title -->
        <input
          :value="task.text"
          @change="onTextChange"
          class="bg-transparent text-xl font-semibold outline-none border-b border-white/20 focus:border-white/50 pb-1 w-full"
          placeholder="Task title" />

        <!-- Status -->
        <div class="flex items-center gap-3">
          <label class="text-xs text-white/50 uppercase tracking-wide">Status</label>
          <select
            :value="task.status"
            @change="onStatusChange"
            class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none">
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
            <option value="skipped">Skipped</option>
            <option value="blocked">Blocked</option>
          </select>
        </div>

        <!-- Schedule / Location -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-white/50 uppercase tracking-wide">Location</span>
          <template v-if="isBacklog">
            <div class="text-xs text-white/30 italic mb-1">Unscheduled (backlog)</div>
            <div class="flex items-center gap-2">
              <input v-model="scheduleDate" type="date"
                     class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none" />
              <select v-model="scheduleAnchor"
                      class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none">
                <option v-for="a in anchorStore.anchors" :key="a.id" :value="a.id">{{ a.name }}</option>
              </select>
              <button @click="scheduleTask"
                      class="text-xs px-3 py-1 rounded bg-blue-500/20 text-blue-300 hover:bg-blue-500/30">
                Schedule
              </button>
            </div>
          </template>
          <template v-else>
            <div class="flex items-center gap-2 text-sm">
              <span class="text-white/60">{{ planStore.activeDate }}</span>
              <span class="text-white/40">·</span>
              <select :value="anchorId" @change="moveToAnchor(($event.target as HTMLSelectElement).value)"
                      class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none">
                <option v-for="a in anchorStore.anchors" :key="a.id" :value="a.id">{{ a.name }}</option>
              </select>
            </div>
            <button @click="moveToBacklog"
                    class="text-xs text-white/40 hover:text-white/70 self-start">
              Move to backlog
            </button>
          </template>
        </div>

        <!-- Description -->
        <div class="flex flex-col gap-1">
          <label class="text-xs text-white/50 uppercase tracking-wide">Description</label>
          <textarea
            :value="task.description ?? ''"
            @blur="onDescBlur"
            rows="3"
            placeholder="Add a description..."
            class="bg-gray-800 text-sm text-white/80 rounded px-3 py-2 border border-white/10 outline-none focus:border-white/30 resize-none" />
        </div>

        <!-- Subtasks -->
        <div class="flex flex-col gap-2">
          <div class="flex items-center gap-2">
            <span class="text-xs text-white/50 uppercase tracking-wide">Subtasks</span>
            <span class="text-xs text-white/30">{{ subtasksDone }}/{{ subtasks.length }}</span>
          </div>
          <ul class="flex flex-col gap-1">
            <li v-for="s in subtasks" :key="s.id" class="flex items-center gap-2 group">
              <input
                type="checkbox"
                :checked="s.done"
                @change="updateSubtask(s.id, { done: !s.done })"
                class="accent-green-400 flex-shrink-0" />
              <span :class="s.done ? 'line-through text-white/30' : 'text-white/80'" class="flex-1 text-sm">{{ s.text }}</span>
              <button
                @click="removeSubtask(s.id)"
                class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
            </li>
          </ul>
          <div class="flex gap-2">
            <input
              v-model="newSubtaskText"
              @keydown.enter="addSubtask"
              placeholder="Add subtask..."
              class="flex-1 bg-gray-800 text-sm text-white/80 rounded px-2 py-1 border border-white/10 outline-none focus:border-white/30" />
            <button
              @click="addSubtask"
              class="text-xs text-white/40 hover:text-white/70 px-2">Add</button>
          </div>
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

          <!-- Blocked by -->
          <div class="flex flex-col gap-1">
            <span class="text-xs text-white/40">Blocked by</span>
            <div v-if="!deps.blocked_by.length" class="text-xs text-white/20 italic">None</div>
            <button
              v-for="d in deps.blocked_by" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span :class="STATUS_COLORS['pending']" class="w-2 h-2 rounded-full flex-shrink-0" />
              <span class="text-sm text-white/70 hover:text-white flex-1 truncate">{{ d.name || depLabel(d.type, d.entity_id) }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/40">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <!-- Blocks -->
          <div class="flex flex-col gap-1">
            <span class="text-xs text-white/40">Blocks</span>
            <div v-if="!deps.blocks.length" class="text-xs text-white/20 italic">None</div>
            <button
              v-for="d in deps.blocks" :key="d.id"
              @click="openDep(d.type, d.entity_id)"
              class="flex items-center gap-2 text-left group">
              <span :class="STATUS_COLORS['pending']" class="w-2 h-2 rounded-full flex-shrink-0" />
              <span class="text-sm text-white/70 hover:text-white flex-1 truncate">{{ d.name || depLabel(d.type, d.entity_id) }}</span>
              <span class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/40">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" class="text-white/20 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100">✕</button>
            </button>
          </div>

          <SearchAutocomplete :search-fn="searchForDependency" placeholder="Search tasks/milestones..." @select="addDependencyFromSearch" />
        </div>

        <!-- Milestones -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-white/50 uppercase tracking-wide">Milestones</span>
          <div v-if="!(milestoneStore.taskMilestones[taskId] ?? []).length" class="text-xs text-white/20 italic">None</div>
          <button
            v-for="m in (milestoneStore.taskMilestones[taskId] ?? [])" :key="m.id"
            @click="openMilestone(m.id)"
            class="flex items-center gap-2 text-left">
            <span v-if="m.color" class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: m.color }" />
            <span class="text-sm text-white/70 hover:text-white"
                  :style="m.color ? { color: m.color } : {}">{{ m.name }}</span>
            <span class="text-xs px-1 py-0.5 rounded text-white/40"
                  :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
                  :class="m.color ? 'border' : 'bg-white/10'">{{ m.status }}</span>
          </button>
          <SearchAutocomplete :search-fn="searchForMilestone" placeholder="Search milestones..." @select="linkMilestoneFromSearch" />
        </div>

        <!-- Context entries -->
        <div class="flex flex-col gap-2">
          <span class="text-xs text-white/50 uppercase tracking-wide">Context</span>
          <div v-if="!contexts.length" class="text-xs text-white/20 italic">None</div>
          <div v-for="subject in contexts" :key="subject"
               class="flex items-center justify-between text-sm">
            <router-link :to="'/context'" class="text-white/70 hover:text-white">{{ subject }}</router-link>
            <button @click="unlinkContext(subject)" class="text-white/20 hover:text-white/50 text-xs ml-2">✕</button>
          </div>
          <SearchAutocomplete :search-fn="searchForContext" placeholder="Link context entry..." @select="linkContextFromSearch" />
        </div>

        <!-- Follow-up config -->
        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <span class="text-xs text-white/50 uppercase tracking-wide">Follow-up</span>
            <button @click="showFollowup = !showFollowup" class="text-xs text-white/40 hover:text-white/70">
              {{ showFollowup ? 'Hide' : 'Edit' }}
            </button>
          </div>
          <div v-if="task.followup_config && !showFollowup" class="text-xs text-white/40">
            {{ task.followup_config.enabled ? `Enabled — pre every ${task.followup_config.pre_ack_interval_min}m` : 'Disabled (override)' }}
          </div>
          <div v-else-if="!task.followup_config && !showFollowup" class="text-xs text-white/20 italic">Using anchor default</div>
          <div v-if="showFollowup" class="flex flex-col gap-2 bg-gray-800 rounded p-3 border border-white/10">
            <label class="flex items-center gap-2 text-xs text-white/70">
              <input
                type="checkbox"
                :checked="task.followup_config?.enabled ?? false"
                @change="(e) => toggleFollowup((e.target as HTMLInputElement).checked)"
                class="accent-blue-400" />
              Override anchor follow-up
            </label>
            <template v-if="task.followup_config?.enabled">
              <div class="grid grid-cols-2 gap-2 text-xs text-white/50">
                <label class="flex flex-col gap-0.5">
                  Pre interval (min)
                  <input
                    :value="task.followup_config.pre_ack_interval_min"
                    type="number" min="1"
                    @change="patchFollowup({ pre_ack_interval_min: +($event.target as HTMLInputElement).value })"
                    class="bg-gray-700 text-white rounded px-1.5 py-0.5 outline-none w-16" />
                </label>
                <label class="flex flex-col gap-0.5">
                  Max pings
                  <input
                    :value="task.followup_config.pre_ack_max_pings"
                    type="number" min="1"
                    @change="patchFollowup({ pre_ack_max_pings: +($event.target as HTMLInputElement).value })"
                    class="bg-gray-700 text-white rounded px-1.5 py-0.5 outline-none w-16" />
                </label>
                <label class="flex flex-col gap-0.5">
                  Post interval (min)
                  <input
                    :value="task.followup_config.post_ack_interval_min"
                    type="number" min="1"
                    @change="patchFollowup({ post_ack_interval_min: +($event.target as HTMLInputElement).value })"
                    class="bg-gray-700 text-white rounded px-1.5 py-0.5 outline-none w-16" />
                </label>
                <label class="flex flex-col gap-0.5">
                  Post pings
                  <input
                    :value="task.followup_config.post_ack_pings"
                    type="number" min="1"
                    @change="patchFollowup({ post_ack_pings: +($event.target as HTMLInputElement).value })"
                    class="bg-gray-700 text-white rounded px-1.5 py-0.5 outline-none w-16" />
                </label>
              </div>
            </template>
          </div>
        </div>

        <!-- Delete -->
        <div class="mt-auto pt-4 border-t border-white/10">
          <button @click="deleteTask" class="text-red-400 hover:text-red-300 text-sm">Delete task</button>
        </div>

      </template>
  </div>
</template>
