<script setup lang="ts">
import { ref } from 'vue'
import type { Task, TaskStatus } from '../stores/plan'
import type { FollowupConfig } from '../stores/anchors'
import { useMilestoneStore } from '../stores/milestones'
const milestoneStore = useMilestoneStore()

const props = defineProps<{ task: Task }>()
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
</script>

<template>
  <li class="flex gap-2 items-center group">
    <button
      @click="cycleStatus"
      :class="STATUS_COLORS[task.status]"
      :title="task.status"
      class="w-2.5 h-2.5 rounded-full flex-shrink-0 mt-0.5 transition-colors cursor-pointer" />
    <input
      :value="task.text"
      :class="task.status === 'done' ? 'line-through opacity-40' : ''"
      @change="updateText"
      class="flex-1 bg-transparent border-b border-white/20 focus:border-white/60 outline-none text-sm py-0.5" />
    <span
      v-for="m in (milestoneStore.taskMilestones[task.id] ?? [])" :key="m.id"
      class="text-xs px-1 py-0.5 rounded bg-white/10 text-white/50 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
      {{ m.name }}
    </span>
    <button
      @click="emit('remove')"
      class="text-white/30 hover:text-white/70 text-xs opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
    <div>
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
  </li>
</template>
