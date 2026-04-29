<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Anchor } from '../stores/anchors'
import MotifPicker, { type MotifSlot } from './MotifPicker.vue'

const props = withDefaults(defineProps<{
  anchor: Anchor
  isPending?: boolean
}>(), { isPending: false })

const emit = defineEmits<{
  save: [anchor: Anchor]
  delete: [anchorId: string]
  discard: []
  moveUp: [anchorId: string]
  moveDown: [anchorId: string]
}>()

const draft = ref({ ...props.anchor })
const saving = ref(false)

watch(() => props.anchor, (a) => { draft.value = { ...a } }, { deep: true })

// Compute end time from start + duration
const endTime = computed({
  get() {
    if (!draft.value.time) return ''
    const [h, m] = draft.value.time.split(':').map(Number)
    const total = h * 60 + m + draft.value.duration_minutes
    const eh = Math.floor(total / 60) % 24
    const em = total % 60
    return `${String(eh).padStart(2, '0')}:${String(em).padStart(2, '0')}`
  },
  set(val: string) {
    if (!draft.value.time || !val) return
    const [sh, sm] = draft.value.time.split(':').map(Number)
    const [eh, em] = val.split(':').map(Number)
    let diff = (eh * 60 + em) - (sh * 60 + sm)
    if (diff <= 0) diff += 24 * 60 // wrap past midnight
    draft.value.duration_minutes = diff
  },
})

async function save() {
  saving.value = true
  emit('save', { ...draft.value })
  saving.value = false
}
</script>

<template>
  <div class="bg-white/5 border rounded-xl p-4 flex flex-col gap-3"
       :class="isPending ? 'border-blue-400/40' : 'border-white/10'">
    <div class="flex items-center gap-3">
      <input v-model="draft.name" placeholder="Anchor name"
             class="bg-transparent font-semibold text-white flex-1 outline-none border-b border-white/20 pb-0.5"
             :class="isPending ? 'border-blue-400/40' : ''" />
    </div>
    <div data-testid="anchor-motif-picker">
      <MotifPicker
        :model-value="(draft.motif as MotifSlot | null | undefined) ?? null"
        @update:model-value="(slot) => draft.motif = slot"
      />
    </div>

    <div class="grid grid-cols-4 gap-3 text-sm">
      <label class="flex flex-col gap-1 text-white/50">
        Start
        <input v-model="draft.time" type="time"
               class="bg-white/10 text-white rounded-lg px-3 py-1.5 outline-none" />
      </label>
      <label class="flex flex-col gap-1 text-white/50">
        End
        <input :value="endTime" @change="endTime = ($event.target as HTMLInputElement).value" type="time"
               class="bg-white/10 text-white rounded-lg px-3 py-1.5 outline-none" />
      </label>
      <label class="flex flex-col gap-1 text-white/50">
        Duration
        <div class="flex items-center gap-1">
          <input :value="Math.floor(draft.duration_minutes / 60)" type="number" min="0" max="23"
                 @change="draft.duration_minutes = +($event.target as HTMLInputElement).value * 60 + (draft.duration_minutes % 60)"
                 class="bg-white/10 text-white rounded-lg px-2 py-1.5 outline-none w-12 text-center" />
          <span class="text-white/30 text-xs">h</span>
          <input :value="draft.duration_minutes % 60" type="number" min="0" max="59" step="5"
                 @change="draft.duration_minutes = Math.floor(draft.duration_minutes / 60) * 60 + +($event.target as HTMLInputElement).value"
                 class="bg-white/10 text-white rounded-lg px-2 py-1.5 outline-none w-12 text-center" />
          <span class="text-white/30 text-xs">m</span>
        </div>
      </label>
      <label class="flex flex-col gap-1 text-white/50">
        Flexibility
        <select v-model="draft.flexibility"
                class="bg-white/10 text-white rounded-lg px-3 py-1.5 outline-none">
          <option value="locked">Locked</option>
          <option value="flexible">Flexible</option>
          <option value="skippable">Skippable</option>
        </select>
      </label>
    </div>

    <!-- Follow-up config section -->
    <details v-if="!isPending" class="text-sm">
      <summary class="cursor-pointer text-white/50 hover:text-white/80 select-none py-1">
        Follow-up config
      </summary>
      <div class="mt-2 space-y-3 bg-white/5 rounded-lg p-3">
        <label class="flex items-center gap-2">
          <input type="checkbox"
                 :checked="draft.followup_config?.enabled ?? false"
                 @change="(e) => {
                   const en = (e.target as HTMLInputElement).checked
                   draft.followup_config = draft.followup_config
                     ? { ...draft.followup_config, enabled: en }
                     : { enabled: en, pre_ack_interval_min: 5, pre_ack_max_pings: 3,
                         post_ack_interval_min: 15, post_ack_pings: 2 }
                 }"
                 class="accent-blue-400" />
          <span class="text-white/70">Enable follow-up pings</span>
        </label>
        <template v-if="draft.followup_config?.enabled">
          <div class="grid grid-cols-2 gap-3">
            <label class="flex flex-col gap-1 text-white/50 text-xs">
              Pre-ack interval (min)
              <input v-model.number="draft.followup_config.pre_ack_interval_min" type="number" min="1"
                     class="bg-white/10 text-white rounded px-2 py-1 outline-none" />
            </label>
            <label class="flex flex-col gap-1 text-white/50 text-xs">
              Max pre-ack pings
              <input v-model.number="draft.followup_config.pre_ack_max_pings" type="number" min="1"
                     class="bg-white/10 text-white rounded px-2 py-1 outline-none" />
            </label>
            <label class="flex flex-col gap-1 text-white/50 text-xs">
              Post-ack interval (min)
              <input v-model.number="draft.followup_config.post_ack_interval_min" type="number" min="1"
                     class="bg-white/10 text-white rounded px-2 py-1 outline-none" />
            </label>
            <label class="flex flex-col gap-1 text-white/50 text-xs">
              Post-ack pings
              <input v-model.number="draft.followup_config.post_ack_pings" type="number" min="1"
                     class="bg-white/10 text-white rounded px-2 py-1 outline-none" />
            </label>
          </div>
        </template>
      </div>
    </details>

    <div class="flex items-center gap-2 justify-between">
      <div v-if="!isPending" class="flex gap-1">
        <button @click="emit('moveUp', anchor.id)" title="Move up"
                class="px-2 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white/50">▲</button>
        <button @click="emit('moveDown', anchor.id)" title="Move down"
                class="px-2 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white/50">▼</button>
      </div>
      <div v-else />
      <div class="flex gap-2">
        <button v-if="isPending" @click="emit('discard')"
                class="px-4 py-1.5 bg-white/10 hover:bg-white/20 text-white/50 rounded-lg text-sm">
          Cancel
        </button>
        <button v-if="!isPending" @click="emit('delete', anchor.id)"
                class="px-4 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm">
          Delete
        </button>
        <button @click="save" :disabled="saving || !draft.name || !draft.time"
                class="px-4 py-1.5 bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 rounded-lg text-sm disabled:opacity-30">
          {{ isPending ? 'Create' : (saving ? 'Saving…' : 'Save') }}
        </button>
      </div>
    </div>
  </div>
</template>
