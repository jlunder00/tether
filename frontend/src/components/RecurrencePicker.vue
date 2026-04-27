<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  modelValue: string | null
  startTime: string  // ISO 8601 — used to derive day-of-week for weekly preset
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

type Preset = 'none' | 'daily' | 'weekly' | 'weekdays' | 'monthly' | 'custom'

const DOW_NAMES: readonly string[] = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA']

/** Derive BYDAY abbreviation from an ISO start_time string. */
function dowFromISO(iso: string): string {
  return DOW_NAMES[new Date(iso).getDay()]
}

/** Map a known rrule string to its preset key, or 'custom' if unrecognised. */
function rruleToPreset(rrule: string | null): Preset {
  if (!rrule) return 'none'
  if (rrule === 'FREQ=DAILY') return 'daily'
  if (rrule.startsWith('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')) return 'weekdays'
  if (/^FREQ=WEEKLY;BYDAY=[A-Z]{2}$/.test(rrule)) return 'weekly'
  if (rrule === 'FREQ=MONTHLY') return 'monthly'
  return 'custom'
}

// Local preset tracks UI selection independently of modelValue so that choosing
// "Custom" immediately shows the text input without needing the parent to round-trip.
const localPreset = ref<Preset>(rruleToPreset(props.modelValue))

// Sync inbound modelValue changes (e.g. parent reset) back to localPreset
watch(() => props.modelValue, (v) => {
  localPreset.value = rruleToPreset(v)
})

// Holds the raw text when user picks "custom"
const customRrule = ref<string>(
  localPreset.value === 'custom' ? (props.modelValue ?? '') : '',
)

function onPresetChange(e: Event) {
  const preset = (e.target as HTMLSelectElement).value as Preset
  localPreset.value = preset
  switch (preset) {
    case 'none':
      emit('update:modelValue', null)
      break
    case 'daily':
      emit('update:modelValue', 'FREQ=DAILY')
      break
    case 'weekly':
      emit('update:modelValue', `FREQ=WEEKLY;BYDAY=${dowFromISO(props.startTime)}`)
      break
    case 'weekdays':
      emit('update:modelValue', 'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')
      break
    case 'monthly':
      emit('update:modelValue', 'FREQ=MONTHLY')
      break
    case 'custom':
      // Don't emit yet — wait for the text input
      customRrule.value = props.modelValue ?? ''
      break
  }
}

function onCustomChange(e: Event) {
  const val = (e.target as HTMLInputElement).value.trim()
  customRrule.value = val
  if (val) emit('update:modelValue', val)
}
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <label class="text-xs text-white/40">Repeat</label>
    <select
      :value="localPreset"
      @change="onPresetChange"
      class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none focus:border-white/40"
    >
      <option value="none">Does not repeat</option>
      <option value="daily">Daily</option>
      <option value="weekly">Weekly</option>
      <option value="weekdays">Every weekday (Mon–Fri)</option>
      <option value="monthly">Monthly</option>
      <option value="custom">Custom (RRULE)</option>
    </select>
    <input
      v-if="localPreset === 'custom'"
      data-testid="rrule-custom-input"
      type="text"
      :value="customRrule"
      placeholder="e.g. FREQ=WEEKLY;BYDAY=MO,WE"
      @change="onCustomChange"
      class="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-white/20 outline-none focus:border-white/40 font-mono"
    />
  </div>
</template>
