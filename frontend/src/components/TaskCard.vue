<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import type { Task, TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { usePlanStore } from '../stores/plan'
const milestoneStore = useMilestoneStore()
const planStore = usePlanStore()
const router = useRouter()
const route = useRoute()

// Derive the route base for detail panel navigation based on current view
const routeBase = computed(() => {
  if (route.path.startsWith('/kanban')) return '/kanban'
  if (route.path.startsWith('/dashboard')) return '/dashboard'
  return `/plan/day/${planStore.activeDate}`
})

const props = withDefaults(defineProps<{
  task: Task
  editable?: boolean
  showRemove?: boolean
  showDetailLink?: boolean
  compact?: boolean
  hideTags?: boolean  // hide milestone/context tags (when inside a GroupContainer that already shows them)
}>(), {
  editable: true,
  showRemove: true,
  showDetailLink: true,
  compact: false,
  hideTags: false,
})
const emit = defineEmits<{
  (e: 'update', task: Task): void
  (e: 'remove'): void
}>()

// Status pill colors (text + bg for the clickable pill)
const STATUS_PILL: Record<TaskStatus, { bg: string; text: string; label: string }> = {
  pending:     { bg: 'bg-white/10', text: 'text-white/50', label: 'todo' },
  in_progress: { bg: 'bg-blue-500/20', text: 'text-blue-300', label: 'doing' },
  done:        { bg: 'bg-green-500/20', text: 'text-green-300', label: 'done' },
  skipped:     { bg: 'bg-orange-500/20', text: 'text-orange-300', label: 'skip' },
  blocked:     { bg: 'bg-red-500/20', text: 'text-red-300', label: 'blocked' },
}

// Card background tint derived from status
const STATUS_CARD_BG: Record<TaskStatus, string> = {
  pending:     'bg-white/[0.04]',
  in_progress: 'bg-blue-500/[0.06]',
  done:        'bg-green-500/[0.04] opacity-70',
  skipped:     'bg-orange-500/[0.04] opacity-50',
  blocked:     'bg-red-500/[0.06]',
}

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

</script>

<template>
  <div class="group rounded-lg transition-colors border border-white/[0.08] cursor-pointer relative"
      :class="STATUS_CARD_BG[task.status]"
      @click="task.id && router.push(`${routeBase}/task/${task.id}`)">
    <div class="flex flex-col gap-1 p-2">
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
             class="fixed z-50 bg-gray-800 border border-white/20 rounded-lg shadow-xl py-1 min-w-[100px]"
             :style="statusDropdownStyle">
          <button
            v-for="s in ALL_STATUSES" :key="s"
            @click.stop="setStatus(s)"
            :class="[STATUS_PILL[s].bg, STATUS_PILL[s].text, s === task.status ? 'ring-1 ring-white/30' : '']"
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
        class="w-full bg-transparent border-b border-white/20 focus:border-white/60 outline-none text-sm py-0.5" />
      <span
        v-else
        class="text-sm break-words"
        :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
    </div>

    <!-- Tags row (milestone + context + schedule) — hidden when inside a GroupContainer that shows them -->
    <div v-if="!hideTags && (milestoneStore.taskMilestones[task.id]?.length || task.context_subject || (task as any).plan_date)" class="flex flex-wrap gap-1">
      <span
        v-if="(task as any).plan_date"
        @click.stop
        class="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300">
        {{ (task as any).plan_date }}{{ (task as any).anchor_id ? ' · ' + (task as any).anchor_id : '' }}
      </span>
      <span
        v-if="task.context_subject"
        @click.stop
        class="text-[10px] px-1.5 py-0.5 rounded bg-white/10 text-white/40">
        {{ task.context_subject }}
      </span>
      <span
        v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
        @click.stop="router.push(`/plan/day/${planStore.activeDate}/milestone/${m.id}`)"
        :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
        class="text-[10px] px-1.5 py-0.5 rounded border cursor-pointer"
        :class="m.color ? '' : 'bg-white/10 text-white/50 border-transparent hover:bg-white/20'">
        {{ m.name }}
      </span>
    </div>

    <!-- Action buttons (visible on hover) -->
    <div v-if="showRemove || (showDetailLink && !compact)" class="flex gap-1 justify-end">
      <button
        v-if="showRemove"
        @click.stop="emit('remove')"
        class="text-white/30 hover:text-white/70 text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
    </div>
    <div v-if="showDetailLink && !compact">
      <button
        @click="openFollowup"
        class="text-white/20 hover:text-white/50 text-xs opacity-0 group-hover:opacity-100 transition-opacity ml-1">
        ⚙
      </button>
      <Teleport to="body">
      <div v-if="showFollowup"
           class="fixed z-50 bg-gray-800 border border-white/20 rounded-xl p-3 min-w-[200px] shadow-xl"
           :style="popoverStyle">
        <label class="flex items-center gap-2 text-xs text-white/70 mb-2">
          <input type="checkbox"
                 :checked="task.followup_config?.enabled ?? false"
                 @change="(e) => toggleFollowup((e.target as HTMLInputElement).checked)"
                 class="accent-blue-400" />
          Override anchor follow-up
        </label>
        <template v-if="task.followup_config?.enabled">
          <div class="grid grid-cols-2 gap-2 text-xs text-white/50">
            <label class="flex flex-col gap-0.5">
              Pre interval
              <input
                :value="task.followup_config.pre_ack_interval_min"
                type="number" min="1"
                @change="emit('update', { ...task, followup_config: { ...task.followup_config!, pre_ack_interval_min: +($event.target as HTMLInputElement).value } })"
                class="bg-white/10 text-white rounded px-1.5 py-0.5 outline-none w-16" />
            </label>
            <label class="flex flex-col gap-0.5">
              Max pings
              <input
                :value="task.followup_config.pre_ack_max_pings"
                type="number" min="1"
                @change="emit('update', { ...task, followup_config: { ...task.followup_config!, pre_ack_max_pings: +($event.target as HTMLInputElement).value } })"
                class="bg-white/10 text-white rounded px-1.5 py-0.5 outline-none w-16" />
            </label>
          </div>
        </template>
        <button @click="showFollowup = false" class="mt-2 text-xs text-white/40 hover:text-white/70 w-full text-right">
          done
        </button>
      </div>
      </Teleport>
    </div>
  </div>
  </div>
</template>
