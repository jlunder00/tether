<script setup lang="ts">
import { ref, watch } from 'vue'
import type { Anchor } from '../stores/anchors'

const props = defineProps<{ anchor: Anchor }>()
const emit = defineEmits<{
  save: [anchor: Anchor]
  delete: [anchorId: string]
  moveUp: [anchorId: string]
  moveDown: [anchorId: string]
}>()

const draft = ref({ ...props.anchor })
const saving = ref(false)

watch(() => props.anchor, (a) => { draft.value = { ...a } }, { deep: true })

async function save() {
  saving.value = true
  await emit('save', { ...draft.value })
  saving.value = false
}
</script>

<template>
  <div class="bg-white/5 border border-white/10 rounded-xl p-4 flex flex-col gap-3">
    <div class="flex items-center gap-3">
      <div class="w-3 h-3 rounded-full flex-shrink-0" :style="{ background: draft.color }" />
      <input v-model="draft.name"
             class="bg-transparent font-semibold text-white flex-1 outline-none border-b border-white/20 pb-0.5" />
    </div>

    <div class="grid grid-cols-2 gap-3 text-sm">
      <label class="flex flex-col gap-1 text-white/50">
        Time
        <input v-model="draft.time" type="time"
               class="bg-white/10 text-white rounded-lg px-3 py-1.5 outline-none" />
      </label>
      <label class="flex flex-col gap-1 text-white/50">
        Duration (min)
        <input v-model.number="draft.duration_minutes" type="number" min="5" step="5"
               class="bg-white/10 text-white rounded-lg px-3 py-1.5 outline-none" />
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
      <label class="flex flex-col gap-1 text-white/50">
        Color
        <input v-model="draft.color" type="color"
               class="bg-white/10 rounded-lg h-9 w-full cursor-pointer" />
      </label>
    </div>

    <!-- Follow-up config section -->
    <details class="text-sm">
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
      <div class="flex gap-1">
        <button @click="emit('moveUp', anchor.id)" title="Move up"
                class="px-2 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white/50">▲</button>
        <button @click="emit('moveDown', anchor.id)" title="Move down"
                class="px-2 py-1.5 bg-white/10 hover:bg-white/20 rounded-lg text-sm text-white/50">▼</button>
      </div>
      <div class="flex gap-2">
        <button @click="emit('delete', anchor.id)"
                class="px-4 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm">
          Delete
        </button>
        <button @click="save" :disabled="saving"
                class="px-4 py-1.5 bg-white/20 hover:bg-white/30 rounded-lg text-sm disabled:opacity-50">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
    </div>
  </div>
</template>
