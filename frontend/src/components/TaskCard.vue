<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Task, TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { useSlideOver } from '../composables/useSlideOver'
const milestoneStore = useMilestoneStore()
const { push: pushPanel } = useSlideOver()

const props = withDefaults(defineProps<{
  task: Task
  editable?: boolean
  showRemove?: boolean
  showDetailLink?: boolean
  compact?: boolean
  hideTags?: boolean  // hide milestone/context tags (when inside a GroupContainer that already shows them)
  navigable?: boolean  // whether clicking the card navigates to detail panel
}>(), {
  editable: true,
  showRemove: true,
  showDetailLink: true,
  compact: false,
  hideTags: false,
  navigable: true,
})
const emit = defineEmits<{
  (e: 'update', task: Task): void
  (e: 'remove'): void
}>()

// Status pill colors (text + bg for the clickable pill)
const STATUS_PILL: Record<TaskStatus, { bg: string; text: string; label: string }> = {
  pending:     { bg: 'bg-[--status-todo-bg]', text: 'text-[--status-todo-fg]', label: 'todo' },
  in_progress: { bg: 'bg-[--status-doing-bg]', text: 'text-[--status-doing-fg]', label: 'doing' },
  done:        { bg: 'bg-[--status-done-bg]', text: 'text-[--status-done-fg]', label: 'done' },
  skipped:     { bg: 'bg-[--status-skip-bg]', text: 'text-[--status-skip-fg]', label: 'skip' },
  blocked:     { bg: 'bg-[--status-block-bg]', text: 'text-[--status-block-fg]', label: 'blocked' },
}

// Tasks are transparent — the parent AnchorBlock's --m-band provides the surface.
// Status is communicated by text dimming + pill + per-task sidebar line only.
const STATUS_ROW_STYLE: Record<TaskStatus, Record<string, string>> = {
  pending:     {},
  in_progress: {},
  done:        { opacity: '0.55' },
  skipped:     { opacity: '0.45' },
  blocked:     {},
}

const isOverdue = computed(() => {
  const pd = (props.task as any).plan_date as string | null | undefined
  if (!pd) return false
  if (props.task.status === 'done' || props.task.status === 'skipped') return false
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return pd < today
})

const showFollowup = ref(false)
const showStatusDropdown = ref(false)
const popoverStyle = ref({ top: '0px', right: '0px' })
const statusDropdownStyle = ref({ top: '0px', left: '0px' })

function openFollowup(e: MouseEvent) {
  const btn = e.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()
  popoverStyle.value = {
    top: `${rect.bottom + window.scrollY + 4}px`,
    right: `${window.innerWidth - rect.right}px`,
  }
  showFollowup.value = !showFollowup.value
}

function openStatusDropdown(e: MouseEvent) {
  const btn = e.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()
  statusDropdownStyle.value = {
    top: `${rect.bottom + 4}px`,
    left: `${rect.left}px`,
  }
  showStatusDropdown.value = !showStatusDropdown.value
}

function setStatus(status: TaskStatus) {
  emit('update', { ...props.task, status })
  showStatusDropdown.value = false
}

const ALL_STATUSES: TaskStatus[] = ['pending', 'in_progress', 'done', 'skipped', 'blocked']

function updateText(e: Event) {
  emit('update', { ...props.task, text: (e.target as HTMLInputElement).value })
}

function onDragStart(evt: DragEvent) {
  if (!props.task.id) {
    console.warn('[TaskCard] dragstart blocked: task has no id', props.task)
    evt.preventDefault()
    return
  }
  if (!evt.dataTransfer) return
  evt.dataTransfer.effectAllowed = 'move'
  evt.dataTransfer.setData('text/plain', JSON.stringify({ taskId: props.task.id }))
}

function toggleFollowup(enabled: boolean) {
  const fc: FollowupConfig = {
    enabled,
    pre_ack_interval_min: 5,
    pre_ack_max_pings: 3,
    post_ack_interval_min: 15,
    post_ack_pings: 2,
  }
  emit('update', { ...props.task, followup_config: enabled ? fc : null })
}

</script>

<template>
  <div class="group transition-colors cursor-pointer relative"
      :style="STATUS_ROW_STYLE[task.status]"
      :draggable="!editable && !!task.id"
      @dragstart="onDragStart"
      @click="navigable && task.id && pushPanel({ kind: 'task', entityId: task.id })">
    <div v-if="task.color"
         class="absolute left-0 top-1 bottom-1 w-0.5 rounded-full pointer-events-none"
         :style="{ background: task.color }" />
    <div class="flex flex-col gap-1 p-2 pl-3">
    <!-- Status pill (top-right) — dropdown only in editable mode (plan view) -->
    <div class="absolute top-1.5 right-1.5">
      <button
        @click.stop="editable && openStatusDropdown($event)"
        :class="[STATUS_PILL[task.status].bg, STATUS_PILL[task.status].text]"
        class="text-[10px] px-1.5 py-0.5 rounded-full font-medium uppercase tracking-wider leading-none"
        :title="editable ? 'Change status' : task.status">
        {{ STATUS_PILL[task.status].label }}
      </button>
      <Teleport to="body">
        <div v-if="showStatusDropdown"
             class="fixed z-50 bg-[--bg-popover] border border-[--border-2] rounded-lg shadow-xl py-1 min-w-[100px]"
             :style="statusDropdownStyle">
          <button
            v-for="s in ALL_STATUSES" :key="s"
            @click.stop="setStatus(s)"
            :class="[STATUS_PILL[s].bg, STATUS_PILL[s].text, s === task.status ? 'ring-1 ring-[--fg-5]' : '']"
            class="block w-full text-left text-xs px-3 py-1.5 hover:bg-white/10 transition-colors">
            {{ STATUS_PILL[s].label }}
          </button>
        </div>
      </Teleport>
    </div>

    <!-- Title -->
    <div class="pr-14">
      <input
        v-if="editable"
        :value="task.text"
        :class="task.status === 'done' ? 'line-through opacity-40' : ''"
        @click.stop
        @change="updateText"
        class="w-full bg-transparent border-b border-[--border-1] focus:border-[--border-2] outline-none text-sm py-0.5" />
      <span
        v-else
        class="text-sm break-words"
        :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
    </div>

    <!-- Tags row — date/anchor always visible; context/milestone hidden when hideTags (shown by GroupContainer) -->
    <div v-if="(task as any).plan_date || (!hideTags && (milestoneStore.taskMilestones[task.id]?.length || task.context_subject))" class="flex flex-wrap gap-1">
      <span
        v-if="(task as any).plan_date"
        @click.stop
        class="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">
        {{ (task as any).plan_date }}{{ (task as any).anchor_id ? ' · ' + (task as any).anchor_id : '' }}
      </span>
      <span v-if="isOverdue" @click.stop
            class="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 font-medium">
        overdue
      </span>
      <template v-if="!hideTags">
        <span
          v-if="task.context_subject"
          @click.stop
          class="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-[--fg-4]">
          {{ task.context_subject }}
        </span>
        <span
          v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
          @click.stop="pushPanel({ kind: 'milestone', entityId: m.id })"
          :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
          class="text-[10px] px-1.5 py-0.5 rounded border cursor-pointer"
          :class="m.color ? '' : 'bg-white/10 text-[--fg-3] border-transparent hover:bg-white/20'">
          {{ m.name }}
        </span>
      </template>
    </div>

    <!-- Action buttons (visible on hover) -->
    <div v-if="showRemove || (showDetailLink && !compact)" class="flex gap-1 justify-end">
      <button
        v-if="showRemove"
        @click.stop="emit('remove')"
        class="text-[--fg-5] hover:text-[--fg-2] text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
    </div>
    <div v-if="showDetailLink && !compact">
      <button
        @click="openFollowup"
        class="text-[--fg-6] hover:text-[--fg-3] text-xs opacity-0 group-hover:opacity-100 transition-opacity ml-1">
        ⚙
      </button>
      <Teleport to="body">
      <div v-if="showFollowup"
           class="fixed z-50 bg-[--bg-popover] border border-[--border-2] rounded-xl p-3 min-w-[200px] shadow-xl"
           :style="popoverStyle">
        <label class="flex items-center gap-2 text-xs text-[--fg-2] mb-2">
          <input type="checkbox"
                 :checked="task.followup_config?.enabled ?? false"
                 @change="(e) => toggleFollowup((e.target as HTMLInputElement).checked)"
                 class="accent-blue-400" />
          Override anchor follow-up
        </label>
        <template v-if="task.followup_config?.enabled">
          <div class="grid grid-cols-2 gap-2 text-xs text-[--fg-3]">
            <label class="flex flex-col gap-0.5">
              Pre interval
              <input
                :value="task.followup_config.pre_ack_interval_min"
                type="number" min="1"
                @change="emit('update', { ...task, followup_config: { ...task.followup_config!, pre_ack_interval_min: +($event.target as HTMLInputElement).value } })"
                class="bg-white/10 text-[--fg-1] rounded px-1.5 py-0.5 outline-none w-16" />
            </label>
            <label class="flex flex-col gap-0.5">
              Max pings
              <input
                :value="task.followup_config.pre_ack_max_pings"
                type="number" min="1"
                @change="emit('update', { ...task, followup_config: { ...task.followup_config!, pre_ack_max_pings: +($event.target as HTMLInputElement).value } })"
                class="bg-white/10 text-[--fg-1] rounded px-1.5 py-0.5 outline-none w-16" />
            </label>
          </div>
        </template>
        <button @click="showFollowup = false" class="mt-2 text-xs text-[--fg-4] hover:text-[--fg-2] w-full text-right">
          done
        </button>
      </div>
      </Teleport>
    </div>
  </div>
  </div>
</template>
