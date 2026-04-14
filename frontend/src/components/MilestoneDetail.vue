<script setup lang="ts">
import { ref } from 'vue'
import type { Milestone } from '../stores/milestones'
import { useMilestoneStore } from '../stores/milestones'

const props = defineProps<{ milestone: Milestone }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const store = useMilestoneStore()

const editing = ref(false)
const error = ref<string | null>(null)
const editName = ref(props.milestone.name)
const editDesc = ref(props.milestone.description ?? '')
const editDate = ref(props.milestone.target_date ?? '')

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-white/20', in_progress: 'bg-blue-400',
  done: 'bg-green-400', blocked: 'bg-red-400',
}

async function save() {
  try {
    error.value = null
    await store.patchMilestone(props.milestone.id, {
      name: editName.value,
      description: editDesc.value || null,
      target_date: editDate.value || null,
    })
    editing.value = false
  } catch (e) {
    console.error('save error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to save milestone'
  }
}

async function remove() {
  if (!confirm(`Delete milestone "${props.milestone.name}"?`)) return
  try {
    error.value = null
    await store.deleteMilestone(props.milestone.id)
    emit('close')
  } catch (e) {
    console.error('remove error:', e)
    error.value = e instanceof Error ? e.message : 'Failed to delete milestone'
  }
}
</script>

<template>
  <div class="bg-white/5 border border-white/10 rounded-xl p-4 space-y-3 mt-2">
    <p v-if="error" class="text-red-400 text-sm">{{ error }}</p>
    <div class="flex items-center gap-2">
      <span :class="STATUS_COLORS[milestone.status]" class="w-2.5 h-2.5 rounded-full flex-shrink-0" />
      <span v-if="!editing" class="font-semibold text-sm flex-1">{{ milestone.name }}</span>
      <input v-else v-model="editName"
             class="flex-1 bg-transparent border-b border-white/30 outline-none text-sm font-semibold" />
      <button @click="editing = !editing" class="text-xs text-white/40 hover:text-white/70">
        {{ editing ? 'cancel' : 'edit' }}
      </button>
      <button @click="emit('close')" class="text-xs text-white/40 hover:text-white/70">✕</button>
    </div>

    <template v-if="editing">
      <textarea v-model="editDesc" placeholder="Description…"
        class="w-full bg-transparent border border-white/20 rounded p-2 text-xs outline-none resize-none h-16" />
      <input v-model="editDate" type="date"
        class="bg-transparent border-b border-white/20 outline-none text-xs" />
      <div class="flex gap-2">
        <button @click="save" class="text-xs bg-white/10 hover:bg-white/20 px-2 py-1 rounded">Save</button>
        <button @click="remove" class="text-xs text-red-400 hover:text-red-300">Delete</button>
      </div>
    </template>

    <div class="space-y-1">
      <div class="flex justify-between text-xs text-white/50">
        <span>{{ milestone.done_count }} / {{ milestone.task_count }} tasks done</span>
        <span v-if="milestone.target_date">Due {{ milestone.target_date }}</span>
      </div>
      <div class="h-1.5 bg-white/10 rounded-full overflow-hidden">
        <div class="h-full bg-green-400 rounded-full transition-all"
             :style="{ width: milestone.task_count
               ? `${(milestone.done_count / milestone.task_count) * 100}%` : '0%' }" />
      </div>
    </div>

    <ul class="space-y-1" v-if="milestone.tasks.length">
      <li v-for="task in milestone.tasks" :key="task.id"
          class="flex items-center gap-2 text-xs text-white/60">
        <span :class="task.status === 'done' ? 'bg-green-400'
                    : task.status === 'in_progress' ? 'bg-blue-400' : 'bg-white/20'"
              class="w-2 h-2 rounded-full flex-shrink-0" />
        <span :class="task.status === 'done' ? 'line-through opacity-50' : ''">{{ task.text }}</span>
        <span class="text-white/30 ml-auto">{{ task.plan_date }}</span>
      </li>
    </ul>
    <p v-else class="text-xs text-white/30 italic">No tasks linked yet.</p>
  </div>
</template>
