<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Task, TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import type { CalendarEvent } from '../types/events'
import { useMilestoneStore } from '../stores/milestones'
import { useSlideOver } from '../composables/useSlideOver'
import { useDraggableTask } from '../composables/useDraggableTask'
import type { DraggableTaskContext } from '../composables/useDraggableTask'

const milestoneStore = useMilestoneStore()
const { push: pushPanel } = useSlideOver()

/** Display mode for the card. Controls layout and drag behaviour.
 *  - `plan`             — editable card in an AnchorBlock; drag sourced from wrapper div
 *  - `kanban`           — read-only card; this element IS the drag source
 *  - `calendar-event`  — positioned in a time-grid (absorbs CalendarEventBlock)
 *  - `calendar-sidebar`— read-only compact card in calendar sidebar task list
 */
type TaskCardMode = 'plan' | 'kanban' | 'calendar-event' | 'calendar-sidebar'

const props = withDefaults(defineProps<{
  task: Task
  mode?: TaskCardMode
  editable?: boolean
  showRemove?: boolean
  showDetailLink?: boolean
  compact?: boolean
  hideTags?: boolean  // hide milestone/context tags (when inside a GroupContainer that already shows them)
  navigable?: boolean  // whether clicking the card navigates to detail panel
  // ── calendar-event mode props (mirror CalendarEventBlock) ──────────────────
  /** Optional CalendarEvent provides gcal-badge, recurring indicator, source-aware color */
  event?: CalendarEvent
  heightPx?: number
  topPx?: number
  leftPercent?: number
  widthPercent?: number
  resolvedColor?: string
}>(), {
  mode: 'plan',
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

// ── Drag source — useDraggableTask ────────────────────────────────────────────
// isDragging is set when THIS element is the drag source (kanban, calendar-event,
// calendar-sidebar). In plan mode the AnchorBlock wrapper is the source, so
// isDragging stays false — that's fine; Track 3 will wire the wrapper.
const taskRef = computed(() => props.task)

// In calendar-event mode, enrich the drag payload with event timing so drop
// targets can move the event preserving its duration.
const calendarContext = computed<DraggableTaskContext | undefined>(() => {
  if (props.mode !== 'calendar-event' || !props.event) return undefined
  return {
    fromStartTime: props.event.start_time,
    durationMs: new Date(props.event.end_time).getTime() - new Date(props.event.start_time).getTime(),
  }
})

const { isDragging, dragHandlers } = useDraggableTask(taskRef, calendarContext)

// Whether this card element is itself draggable (not just a container for a
// wrapper-div drag in plan view).
const isSelfDraggable = computed(() =>
  !!props.task.id && (props.mode === 'kanban' || props.mode === 'calendar-event' || props.mode === 'calendar-sidebar' || !props.editable)
)

// Status pill colors (text + bg for the clickable pill)
const STATUS_PILL: Record<TaskStatus, { bg: string; text: string; label: string }> = {
  pending:     { bg: 'bg-[--status-todo-bg]', text: 'text-[--status-todo-fg]', label: 'todo' },
  in_progress: { bg: 'bg-[--status-doing-bg]', text: 'text-[--status-doing-fg]', label: 'doing' },
  done:        { bg: 'bg-[--status-done-bg]', text: 'text-[--status-done-fg]', label: 'done' },
  skipped:     { bg: 'bg-[--status-skip-bg]', text: 'text-[--status-skip-fg]', label: 'skip' },
  blocked:     { bg: 'bg-[--status-block-bg]', text: 'text-[--status-block-fg]', label: 'blocked' },
}

// Compact plan-mode status glyphs — rendered via CSS custom properties and ::before
// pseudo-elements so theme switching (terminal ASCII vs default Unicode) is handled
// by the cascade in themes.css without any JS dependency.
const STATUS_GLYPH_CLASS: Record<TaskStatus, string> = {
  pending:     'status-glyph-pending',
  in_progress: 'status-glyph-in_progress',
  done:        'status-glyph-done',
  skipped:     'status-glyph-skipped',
  blocked:     'status-glyph-blocked',
}

function cycleStatus() {
  const idx = ALL_STATUSES.indexOf(props.task.status)
  const next = ALL_STATUSES[(idx + 1) % ALL_STATUSES.length]
  emit('update', { ...props.task, status: next })
}

// Tasks are transparent — the parent AnchorBlock's --m-band provides the surface.
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

// ── Calendar-event mode: helpers and position/size styles ─────────────────────

function defaultEventColor(ev?: CalendarEvent): string {
  if (!ev || ev.source === 'tether') return ev?.color ?? '#6366f1'
  return '#4285f4'
}

const calendarEventStyle = computed(() => {
  const lp = props.leftPercent ?? 0
  const wp = props.widthPercent ?? 100
  const color = props.resolvedColor ?? defaultEventColor(props.event)
  return {
    position: 'absolute' as const,
    top: `${props.topPx ?? 0}px`,
    height: `${props.heightPx ?? 20}px`,
    left: `calc(${lp}% + ${wp * 0.05}% + 2px)`,
    width: `calc(${wp * 0.9}% - 4px)`,
    backgroundColor: color,
    borderLeft: `3px solid ${color}`,
    opacity: props.event?.source !== 'tether' ? 0.75 : 0.92,
  }
})
</script>

<template>
  <!-- ── calendar-event mode: absorbed from CalendarEventBlock ─────────────── -->
  <div
    v-if="mode === 'calendar-event'"
    v-show="!isDragging"
    data-testid="task-card-calendar-event"
    data-event-block
    class="rounded overflow-hidden text-xs px-1.5 py-0.5 cursor-grab shadow-md hover:brightness-110 transition-all z-10"
    :style="calendarEventStyle"
    :draggable="isSelfDraggable || undefined"
    @dragstart="dragHandlers.onDragStart"
    @dragend="dragHandlers.onDragEnd"
    @click.stop="navigable && task.id && pushPanel({ kind: 'task', entityId: task.id })"
  >
    <div class="flex items-center gap-1 truncate pointer-events-none">
      <!-- gcal badge — shown when the event is from an external calendar -->
      <span
        v-if="event && event.source !== 'tether'"
        data-testid="gcal-badge"
        class="text-[9px] bg-black/20 rounded px-0.5 flex-shrink-0"
        :title="event.source === 'google_calendar' ? 'Synced from Google Calendar' : 'Synced from external source'"
      >{{ event.source === 'google_calendar' ? 'G' : '↗' }}</span>
      <!-- recurring indicator -->
      <span
        v-if="event && (event.is_recurring || event.is_occurrence)"
        data-testid="recurring-indicator"
        class="text-[9px] flex-shrink-0 opacity-80"
        title="Recurring event"
      >↻</span>
      <span class="truncate font-medium text-[--accent-fg]">{{ event?.title ?? task.text }}</span>
    </div>
  </div>

  <!-- ── plan / kanban / calendar-sidebar modes ─────────────────────────────── -->
  <div
    v-else
    data-testid="task-card"
    v-show="!isDragging"
    class="group transition-colors cursor-pointer relative"
    :style="STATUS_ROW_STYLE[task.status]"
    :draggable="isSelfDraggable || undefined"
    @dragstart="dragHandlers.onDragStart"
    @dragend="dragHandlers.onDragEnd"
    @click="navigable && task.id && pushPanel({ kind: 'task', entityId: task.id })"
  >
    <div v-if="task.motif || task.color"
         class="absolute left-0 top-0 bottom-0 w-0.5 rounded-full pointer-events-none"
         :style="{ background: task.motif ? `var(--motif-${task.motif})` : task.color! }" />

    <!-- ── Plan mode: compact inline row (glyph · text · tags) ──────────────── -->
    <template v-if="mode === 'plan'">
      <div class="flex items-start gap-1.5 py-0.5 pl-3 pr-2">
        <!-- Status glyph — clickable, cycles status in order.
             Glyph character is injected via CSS ::before / --glyph-* custom property
             so terminal/dracula themes get ASCII brackets without any JS. -->
        <button
          data-testid="plan-status-glyph"
          @click.stop="editable && cycleStatus()"
          :class="STATUS_GLYPH_CLASS[task.status]"
          class="flex-shrink-0 w-4 font-mono text-xs leading-5 text-[--fg-3] hover:text-[--fg-1] cursor-pointer transition-colors"
          :title="task.status" />

        <!-- Task text — wraps, fills available width -->
        <div class="flex-1 min-w-0">
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

        <!-- Tags — right-justified, shrink-safe, no overlap with text -->
        <div
          v-if="(task as any).plan_date || isOverdue || (!hideTags && (milestoneStore.taskMilestones[task.id]?.length || task.context_subject))"
          class="flex-shrink-0 flex flex-wrap gap-1 justify-end max-w-[40%]">
          <span
            v-if="(task as any).plan_date"
            @click.stop
            class="text-[10px] px-1 py-0.5 rounded bg-purple-500/20 text-purple-300">
            {{ (task as any).plan_date }}
          </span>
          <span v-if="isOverdue" @click.stop
                class="text-[10px] px-1 py-0.5 rounded bg-[--status-block-bg] text-[--status-block-fg] font-medium">
            overdue
          </span>
          <template v-if="!hideTags">
            <span
              v-if="task.context_subject"
              @click.stop
              class="text-[10px] px-1 py-0.5 rounded bg-[--bg-elev-3] text-[--fg-4]">
              {{ task.context_subject }}
            </span>
            <span
              v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
              @click.stop="pushPanel({ kind: 'milestone', entityId: m.id })"
              :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
              class="text-[10px] px-1 py-0.5 rounded border cursor-pointer"
              :class="m.color ? '' : 'bg-[--bg-elev-3] text-[--fg-3] border-transparent hover:bg-[--bg-elev-4]'">
              {{ m.name }}
            </span>
          </template>
        </div>

        <!-- Remove button (hover-only) -->
        <button
          v-if="showRemove"
          @click.stop="emit('remove')"
          class="flex-shrink-0 text-[--fg-5] hover:text-[--fg-2] text-xs opacity-0 group-hover:opacity-100 transition-opacity leading-5">✕</button>
      </div>
    </template>

    <!-- ── Kanban / calendar-sidebar modes: original card layout ────────────── -->
    <template v-else>
    <div class="flex flex-col gap-1 p-2 pl-3">
    <!-- Status pill (top-right) — dropdown only in editable mode -->
    <div class="absolute top-1.5 right-1.5">
      <button
        data-testid="task-card-status-pill"
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
            class="block w-full text-left text-xs px-3 py-1.5 hover:bg-[--bg-elev-3] transition-colors">
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

    <!-- Tags row — date/anchor always visible; context/milestone hidden when hideTags -->
    <div v-if="(task as any).plan_date || (!hideTags && (milestoneStore.taskMilestones[task.id]?.length || task.context_subject))" class="flex flex-wrap gap-1">
      <span
        v-if="(task as any).plan_date"
        @click.stop
        class="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">
        {{ (task as any).plan_date }}{{ (task as any).anchor_id ? ' · ' + (task as any).anchor_id : '' }}
      </span>
      <span v-if="isOverdue" @click.stop
            class="text-[10px] px-1.5 py-0.5 rounded bg-[--status-block-bg] text-[--status-block-fg] font-medium">
        overdue
      </span>
      <template v-if="!hideTags">
        <span
          v-if="task.context_subject"
          @click.stop
          class="text-[10px] px-1.5 py-0.5 rounded bg-[--bg-elev-3] text-[--fg-4]">
          {{ task.context_subject }}
        </span>
        <span
          v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
          @click.stop="pushPanel({ kind: 'milestone', entityId: m.id })"
          :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
          class="text-[10px] px-1.5 py-0.5 rounded border cursor-pointer"
          :class="m.color ? '' : 'bg-[--bg-elev-3] text-[--fg-3] border-transparent hover:bg-[--bg-elev-4]'">
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
                class="bg-[--bg-elev-3] text-[--fg-1] rounded px-1.5 py-0.5 outline-none w-16" />
            </label>
            <label class="flex flex-col gap-0.5">
              Max pings
              <input
                :value="task.followup_config.pre_ack_max_pings"
                type="number" min="1"
                @change="emit('update', { ...task, followup_config: { ...task.followup_config!, pre_ack_max_pings: +($event.target as HTMLInputElement).value } })"
                class="bg-[--bg-elev-3] text-[--fg-1] rounded px-1.5 py-0.5 outline-none w-16" />
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
  </template>
  </div>
</template>

<style scoped>
/* ── Plan-mode compact status glyphs ──────────────────────────────────────────
   Characters are defined as CSS custom properties in themes.css so terminal
   and dracula themes get ASCII bracket notation ([ ] [~] [x] [-] [!]) while
   all other themes use Unicode circles (○ ◑ ● ⊘ ⊗). No JS required. */
.status-glyph-pending::before    { content: var(--glyph-pending); }
.status-glyph-in_progress::before { content: var(--glyph-in-progress); }
.status-glyph-done::before       { content: var(--glyph-done); }
.status-glyph-skipped::before    { content: var(--glyph-skipped); }
.status-glyph-blocked::before    { content: var(--glyph-blocked); }
</style>
