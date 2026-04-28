<script setup lang="ts">
import { ref } from 'vue'
import type { RecurrenceEditScope } from '../types/recurrence'

defineProps<{
  open: boolean
  title?: string
}>()

const emit = defineEmits<{
  (e: 'confirm', scope: RecurrenceEditScope): void
  (e: 'cancel'): void
}>()

const scope = ref<RecurrenceEditScope>('this')

function onConfirm() { emit('confirm', scope.value) }
function onCancel() { emit('cancel') }
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') onCancel()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      data-testid="recurrence-edit-dialog"
      class="fixed inset-0 z-[200] flex items-center justify-center bg-black/60"
      @click.self="onCancel"
      @keydown="onKeydown"
      tabindex="0"
    >
      <div class="w-80 bg-gray-800 border border-white/20 rounded-xl shadow-xl p-4 space-y-3">
        <h3 class="text-sm font-medium text-white">{{ title ?? 'Edit recurring event' }}</h3>
        <div class="flex flex-col gap-1.5">
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="this" data-testid="scope-this" />
            <span>Just this event</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="this_and_future" data-testid="scope-future" />
            <span>This and future events</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-sm text-white/80">
            <input type="radio" v-model="scope" value="all" data-testid="scope-all" />
            <span>All events</span>
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
            class="px-3 py-1 text-xs rounded bg-indigo-500 text-white hover:bg-indigo-400"
            @click="onConfirm"
          >Confirm</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
