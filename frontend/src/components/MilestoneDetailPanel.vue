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

// Patch milestone — routes through store, never calls api() directly
async function patchMilestone(fields: Parameters<typeof milestoneStore.patchMilestone>[1]) {
  if (!milestone.value) return
  await milestoneStore.patchMilestone(props.milestoneId, fields)
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
  patchMilestone({ status: (e.target as HTMLSelectElement).value as Parameters<typeof milestoneStore.patchMilestone>[1]['status'] })
}

function onColorChange(e: Event) {
  patchMilestone({ color: (e.target as HTMLInputElement).value || null })
}

function onStatusOverrideChange(e: Event) {
  patchMilestone({ status_override: (e.target as HTMLInputElement).checked })
}

// Progress bar
const progressPct = computed(() => {
  const m = milestone.value
  if (!m || m.task_count === 0) return 0
  return Math.round((m.done_count / m.task_count) * 100)
})

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
  <!-- dp-shell: motif data-attr drives the left-rail colour via --m token -->
  <div class="dp-shell" :data-motif="milestone?.motif ?? 'focus'">

    <!-- ── Header ────────────────────────────────────────────────────────── -->
    <header class="dp-header">
      <div class="dp-crumbs">
        <span class="dp-crumbs__seg">Milestones</span>
        <template v-if="milestone">
          <span class="dp-crumbs__sep">›</span>
          <span class="dp-crumbs__seg">{{ milestone.context_subject }}</span>
        </template>
      </div>
      <div class="dp-title-row">
        <template v-if="milestone">
          <input
            :value="milestone.name"
            @change="onNameChange"
            class="dp-title"
            placeholder="Milestone name" />
          <span :class="`t-pill t-pill--${milestone.status}`">{{ milestone.status }}</span>
        </template>
        <template v-else>
          <span class="dp-title" style="color: var(--fg-5)">Not found</span>
        </template>
      </div>
    </header>

    <!-- ── Scrollable body ───────────────────────────────────────────────── -->
    <div class="dp-body">

      <div v-if="!milestone" class="dp-section" style="color: var(--fg-5); font-size: 13px;">
        Milestone not found.
      </div>

      <template v-else>

        <!-- ── Details ─────────────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Details</span>
          </header>
          <div class="dp-section__body">

            <div class="dp-field">
              <span class="dp-field__label">Target date</span>
              <input
                type="date"
                :value="milestone.target_date ?? ''"
                @change="onTargetDateChange"
                class="dp-input" />
            </div>

            <div class="dp-field">
              <span class="dp-field__label">Color</span>
              <input
                type="color"
                data-testid="milestone-color-input"
                :value="milestone.color ?? '#888888'"
                @change="onColorChange"
                style="width:32px;height:28px;cursor:pointer;border:1px solid var(--border-1);border-radius:3px;background:transparent;" />
            </div>

            <div class="dp-field">
              <span class="dp-field__label">Override status</span>
              <input
                type="checkbox"
                data-testid="milestone-status-override"
                :checked="!!milestone.status_override"
                @change="onStatusOverrideChange" />
            </div>

            <div v-if="milestone.status_override" class="dp-field">
              <span class="dp-field__label">Status</span>
              <select :value="milestone.status" @change="onStatusChange" class="dp-select">
                <option value="pending">Pending</option>
                <option value="in_progress">In Progress</option>
                <option value="done">Done</option>
                <option value="blocked">Blocked</option>
              </select>
            </div>

          </div>
        </section>

        <!-- ── Motif ──────────────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Motif</span>
          </header>
          <div class="dp-section__body">
            <MotifPicker
              data-testid="milestone-motif-picker"
              :model-value="(milestone.motif as MotifSlot | null | undefined) ?? null"
              @update:model-value="(slot) => patchMilestone({ motif: slot })"
            />
          </div>
        </section>

        <!-- ── Description ─────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Description</span>
          </header>
          <div class="dp-section__body">
            <textarea
              :value="milestone.description ?? ''"
              @blur="onDescBlur"
              rows="3"
              placeholder="Add a description..."
              class="dp-textarea" />
          </div>
        </section>

        <!-- ── Progress ────────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Progress</span>
            <span class="dp-section__meta">{{ milestone.done_count }}/{{ milestone.task_count }}</span>
          </header>
          <div class="dp-section__body">
            <div style="width:100%;height:6px;border-radius:3px;background:var(--bg-elev-3);overflow:hidden;">
              <div
                style="height:100%;background:var(--status-done-bg, #4ade80);transition:width 0.2s;"
                :style="{ width: progressPct + '%' }" />
            </div>
          </div>
        </section>

        <!-- ── Linked tasks ────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Tasks</span>
          </header>
          <div class="dp-section__body">
            <div v-if="!milestone.tasks.length" style="color:var(--fg-5);font-size:13px;font-style:italic;">
              No tasks linked
            </div>
            <div
              v-for="t in milestone.tasks" :key="t.id"
              class="t-row"
              style="cursor:pointer;"
              @click="openTask(t.id)">
              <span :class="`t-pill t-pill--${t.status}`" style="width:8px;height:8px;padding:0;border-radius:50%;flex-shrink:0;" />
              <span style="flex:1;font-size:13px;color:var(--fg-2);">{{ t.text ?? t.id }}</span>
              <span v-if="t.plan_date" style="font-size:11px;color:var(--fg-5);">{{ t.plan_date }}</span>
            </div>
          </div>
        </section>

        <!-- ── Links ──────────────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Links</span>
            <button @click="showAddLink = !showAddLink" class="dp-btn" style="font-size:11px;padding:2px 6px;">+ Add</button>
          </header>
          <div class="dp-section__body">
            <div v-for="l in links" :key="l.id" class="t-row">
              <span>{{ LINK_ICONS[l.category] ?? '📎' }}</span>
              <a :href="l.url" target="_blank" style="flex:1;font-size:13px;color:var(--fg-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                {{ l.label || l.url }}
              </a>
              <span style="font-size:11px;color:var(--fg-5);">{{ l.category }}</span>
              <button @click="removeLink(l.id)" style="font-size:11px;color:var(--fg-5);" class="dp-btn">✕</button>
            </div>
            <div v-if="showAddLink" style="display:flex;flex-direction:column;gap:6px;background:var(--bg-elev-2);border-radius:4px;padding:8px;">
              <input v-model="newLinkUrl" placeholder="URL" class="dp-input" />
              <input v-model="newLinkLabel" placeholder="Label (optional)" class="dp-input" />
              <select v-model="newLinkCategory" class="dp-select">
                <option value="document">Document</option>
                <option value="meeting">Meeting</option>
                <option value="pr">PR</option>
                <option value="issue">Issue</option>
                <option value="other">Other</option>
              </select>
              <div style="display:flex;gap:8px;justify-content:flex-end;">
                <button @click="showAddLink = false" class="dp-btn">Cancel</button>
                <button @click="addLink" class="dp-btn">Add</button>
              </div>
            </div>
          </div>
        </section>

        <!-- ── Dependencies ─────────────────────────────────────── -->
        <section class="dp-section">
          <header class="dp-section__head">
            <span class="dp-section__heading">Dependencies</span>
          </header>
          <div class="dp-section__body">

            <div style="font-size:11px;color:var(--fg-5);text-transform:uppercase;letter-spacing:0.04em;margin-bottom:4px;">Blocked by</div>
            <div v-if="!deps.blocked_by.length" style="font-size:12px;color:var(--fg-5);font-style:italic;">None</div>
            <div
              v-for="d in deps.blocked_by" :key="d.id"
              class="t-row"
              style="cursor:pointer;"
              @click="openDep(d.type, d.entity_id)">
              <span style="width:8px;height:8px;border-radius:50%;background:var(--fg-5);flex-shrink:0;" />
              <span style="flex:1;font-size:13px;color:var(--fg-2);">{{ d.name || d.entity_id }}</span>
              <span style="font-size:11px;color:var(--fg-5);">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" style="font-size:11px;color:var(--fg-5);" class="dp-btn">✕</button>
            </div>

            <div style="font-size:11px;color:var(--fg-5);text-transform:uppercase;letter-spacing:0.04em;margin-top:8px;margin-bottom:4px;">Blocks</div>
            <div v-if="!deps.blocks.length" style="font-size:12px;color:var(--fg-5);font-style:italic;">None</div>
            <div
              v-for="d in deps.blocks" :key="d.id"
              class="t-row"
              style="cursor:pointer;"
              @click="openDep(d.type, d.entity_id)">
              <span style="width:8px;height:8px;border-radius:50%;background:var(--fg-5);flex-shrink:0;" />
              <span style="flex:1;font-size:13px;color:var(--fg-2);">{{ d.name || d.entity_id }}</span>
              <span style="font-size:11px;color:var(--fg-5);">{{ d.type }}</span>
              <button @click.stop="removeDep(d.id)" style="font-size:11px;color:var(--fg-5);" class="dp-btn">✕</button>
            </div>

            <SearchAutocomplete
              :search-fn="searchForDependency"
              placeholder="Search tasks/milestones..."
              @select="addDependencyFromSearch" />
          </div>
        </section>

      </template>
    </div>

    <!-- ── Footer ────────────────────────────────────────────────────────── -->
    <footer class="dp-footer">
      <button
        v-if="milestone"
        data-testid="delete-milestone-btn"
        class="dp-btn dp-btn--ghost-danger"
        @click="deleteMilestone">Delete milestone</button>
      <span v-else />
      <span class="dp-footer__hint"><kbd>⌘</kbd><kbd>⌫</kbd></span>
    </footer>

  </div>
</template>
