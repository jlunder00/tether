<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import type { Task, TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
import { usePlanStore } from '../stores/plan'
const milestoneStore = useMilestoneStore()
const planStore = usePlanStore()
const router = useRouter()

const props = withDefaults(defineProps<{
  task: Task
  editable?: boolean
  showRemove?: boolean
  showDetailLink?: boolean
  compact?: boolean
}>(), {
  editable: true,
  showRemove: true,
  showDetailLink: true,
  compact: false,
})
const emit = defineEmits<{
  (e: 'update', task: Task): void
  (e: 'remove'): void
}>()

const STATUS_CYCLE: TaskStatus[] = ['pending', 'in_progress', 'done']
const STATUS_COLORS: Record<TaskStatus, string> = {
  pending:     'bg-white/20 hover:bg-white/40',
  in_progress: 'bg-blue-400 hover:bg-blue-300',
  done:        'bg-green-400 hover:bg-green-300',
  skipped:     'bg-orange-400 hover:bg-orange-300',
  blocked:     'bg-red-400 hover:bg-red-300',
}

const showFollowup = ref(false)
const popoverStyle = ref({ top: '0px', right: '0px' })

function openFollowup(e: MouseEvent) {
  const btn = e.currentTarget as HTMLElement
  const rect = btn.getBoundingClientRect()
  popoverStyle.value = {
    top: `${rect.bottom + window.scrollY + 4}px`,
    right: `${window.innerWidth - rect.right}px`,
  }
  showFollowup.value = !showFollowup.value
}

function cycleStatus() {
  const idx = STATUS_CYCLE.indexOf(props.task.status)
  const next = STATUS_CYCLE[idx === -1 ? 0 : (idx + 1) % STATUS_CYCLE.length]
  emit('update', { ...props.task, status: next })
}

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

const milestoneColors = computed(() =>
  (milestoneStore.taskMilestones[props.task.id] ?? [])
    .map(m => m.color)
    .filter((c): c is string => c !== null)
)
</script>

<template>
  <li class="group rounded-lg transition-colors"
      :style="milestoneColors.length ? {
        border: `2px solid ${milestoneColors[0]}`,
        padding: compact ? '2px 4px' : '4px 8px',
        outline: milestoneColors.length > 1
          ? `2px solid ${milestoneColors[1]}`
          : undefined,
        outlineOffset: milestoneColors.length > 1 ? '1px' : undefined,
      } : { padding: compact ? '2px 4px' : '4px 8px' }">
    <div class="flex gap-2 items-center">
    <button
      @click="cycleStatus"
      :class="STATUS_COLORS[task.status]"
      :title="task.status"
      class="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5 transition-colors cursor-pointer" />
    <input
      v-if="editable"
      :value="task.text"
      :class="task.status === 'done' ? 'line-through opacity-40' : ''"
      @change="updateText"
      class="flex-1 bg-transparent border-b border-white/20 focus:border-white/60 outline-none text-sm py-0.5" />
    <span
      v-else
      class="flex-1 text-sm"
      :class="task.status === 'done' ? 'line-through opacity-40' : ''">{{ task.text }}</span>
    <span
      v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
      @click="router.push(`/plan/day/${planStore.activeDate}/milestone/${m.id}`)"
      :style="m.color ? { backgroundColor: m.color + '33', color: m.color, borderColor: m.color + '66' } : {}"
      class="text-xs px-1 py-0.5 rounded border flex-shrink-0 cursor-pointer"
      :class="m.color ? '' : 'bg-white/10 text-white/50 border-transparent hover:bg-white/20'">
      {{ m.name }}
    </span>
    <button
      v-if="showRemove"
      @click="emit('remove')"
      class="text-white/30 hover:text-white/70 text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
    <button
      v-if="showDetailLink"
      @click="router.push(`/plan/day/${planStore.activeDate}/task/${task.id}`)"
      class="text-white/20 hover:text-white/50 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
      title="Open details">↗</button>
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
  </li>
</template>
