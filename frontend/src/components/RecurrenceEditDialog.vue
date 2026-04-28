<script setup lang="ts">
import { ref, computed } from 'vue'
import type { RecurrenceEditScope } from '../types/recurrence'

const props = defineProps<{
  visible: boolean
  mode: 'event' | 'task'
  action: 'edit' | 'delete' | 'move'
}>()

const emit = defineEmits<{
  (e: 'confirm', scope: RecurrenceEditScope): void
  (e: 'cancel'): void
}>()

const scope = ref<RecurrenceEditScope>('this')

const noun = computed(() => props.mode === 'event' ? 'event' : 'task')

const heading = computed(() => {
  if (props.action === 'edit') return `Edit recurring ${noun.value}`
  if (props.action === 'delete') return `Delete recurring ${noun.value}`
  return `Move recurring ${noun.value}`
})

const optionLabels = computed(() => {
  const verb = props.action === 'edit' ? 'Edit'
             : props.action === 'delete' ? 'Delete'
             : 'Move'
  return {
    this: `${verb} just this occurrence`,
    this_and_future: `This and future occurrences`,
    all: `All occurrences`,
  }
})

const confirmLabel = computed(() => props.action === 'delete' ? 'Delete' : 'Confirm')
const confirmClass = computed(() =>
  props.action === 'delete'
    ? 'px-3 py-1 text-xs rounded bg-red-500 text-white hover:bg-red-400'
    : 'px-3 py-1 text-xs rounded bg-indigo-500 text-white hover:bg-indigo-400'
)

function onConfirm() { emit('confirm', scope.value) }
function onCancel() { emit('cancel') }
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') onCancel()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      data-testid="recurrence-edit-dialog"
      class="fixed inset-0 z-[200] flex items-center justify-center bg-black/60"
      @click.self="onCancel"
      @keydown="onKeydown"
      tabindex="0"
    >
      <div class="w-80 bg-gray-800 border border-white/20 rounded-xl shadow-xl p-4 space-y-3">
        <h3 class="text-sm font-medium text-white">{{ heading }}</h3>
        <div class="flex flex-col gap-1.5">
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="this" data-testid="scope-this" />
            <span>{{ optionLabels.this }}</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="this_and_future" data-testid="scope-future" />
            <span>{{ optionLabels.this_and_future }}</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="all" data-testid="scope-all" />
            <span>{{ optionLabels.all }}</span>
          </label>
        </div>
        <div class="flex justify-end gap-2 pt-2">
          <button
            data-testid="recurrence-edit-cancel"
            class="px-3 py-1 text-xs rounded text-white/60 hover:text-white hover:bg-white/5"
            @click="onCancel"
          >Cancel</button>
          <button
            data-testid="recurrence-edit-confirm"
            :class="confirmClass"
            @click="onConfirm"
          >{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
