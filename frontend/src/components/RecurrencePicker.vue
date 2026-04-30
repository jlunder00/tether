<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { parseRrule, buildRrule, DOW_CODES, DOW_LABELS, type RruleState } from '../composables/useRruleParser'

const props = defineProps<{
  modelValue: string | null
  startTime: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string | null): void
}>()

function initialState(v: string | null): { state: RruleState; custom: string } {
  if (!v) return { state: parseRrule(null), custom: '' }
  const parsed = parseRrule(v)
  // Anything we don't fully round-trip stays as custom
  if (parsed.freq === 'custom' || (buildRrule(parsed) !== v && parsed.freq !== 'none')) {
    return { state: { ...parsed, freq: 'custom' }, custom: v }
  }
  return { state: parsed, custom: '' }
}

const init = initialState(props.modelValue)
const state = ref<RruleState>(init.state)
const customRrule = ref<string>(init.custom)

watch(() => props.modelValue, (v) => {
  const next = initialState(v)
  state.value = next.state
  customRrule.value = next.custom
})

const startDow = computed(() => {
  const d = new Date(props.startTime)
  return isNaN(d.getTime()) ? 'MO' : DOW_CODES[d.getDay()]
})

function emitValue() {
  if (state.value.freq === 'custom') {
    emit('update:modelValue', customRrule.value || null)
    return
  }
  emit('update:modelValue', buildRrule(state.value))
}

function onFreqChange(e: Event) {
  const newFreq = (e.target as HTMLSelectElement).value as RruleState['freq']
  state.value.freq = newFreq
  if (newFreq === 'weekly' && state.value.byday.length === 0) {
    state.value.byday = [startDow.value]
  }
  if (newFreq === 'monthly' && state.value.monthlyMode === 'byday' && state.value.byday.length === 0) {
    state.value.byday = [startDow.value]
  }
  emitValue()
}

function onIntervalChange(e: Event) {
  state.value.interval = Math.max(1, parseInt((e.target as HTMLInputElement).value) || 1)
  emitValue()
}

function toggleDow(dow: string) {
  const idx = state.value.byday.indexOf(dow)
  if (idx >= 0) state.value.byday.splice(idx, 1)
  else state.value.byday.push(dow)
  emitValue()
}

function onMonthlyModeChange() {
  if (state.value.monthlyMode === 'byday' && state.value.byday.length === 0) {
    state.value.byday = [startDow.value]
  }
  emitValue()
}

function onNthWeekdayChange(e: Event) {
  state.value.nthWeekday = parseInt((e.target as HTMLSelectElement).value) || 1
  emitValue()
}

function onMonthlyDowChange(e: Event) {
  state.value.byday = [(e.target as HTMLSelectElement).value]
  emitValue()
}

function onCountChange(e: Event) {
  state.value.count = Math.max(1, parseInt((e.target as HTMLInputElement).value) || 1)
  emitValue()
}

function onUntilChange(e: Event) {
  state.value.until = (e.target as HTMLInputElement).value
  emitValue()
}

function onCustomInput(e: Event) {
  customRrule.value = (e.target as HTMLInputElement).value.trim()
  emitValue()
}
</script>

<template>
  <div class="space-y-2 text-xs">
    <!-- Frequency -->
    <div class="flex items-center gap-2">
      <label class="text-[--fg-3] w-20 flex-shrink-0">Repeat</label>
      <select
        class="flex-1 bg-[--bg-elev-1] border border-[--border-1] rounded px-2 py-1 text-[--fg-1] text-sm"
        :value="state.freq"
        @change="onFreqChange"
      >
        <option value="none">Does not repeat</option>
        <option value="daily">Daily</option>
        <option value="weekly">Weekly</option>
        <option value="monthly">Monthly</option>
        <option value="yearly">Yearly</option>
        <option value="custom">Custom (RRULE)</option>
      </select>
    </div>

    <!-- Interval (daily/weekly/monthly only) -->
    <div v-if="state.freq === 'daily' || state.freq === 'weekly' || state.freq === 'monthly'" class="flex items-center gap-2">
      <label class="text-[--fg-3] w-20 flex-shrink-0">Every</label>
      <input
        type="number" min="1" max="99"
        class="w-16 bg-[--bg-elev-1] border border-[--border-soft] rounded px-2 py-1 text-[--fg-1] text-xs"
        :value="state.interval"
        @change="onIntervalChange"
      />
      <span class="text-[--fg-4]">{{ state.freq === 'daily' ? 'day(s)' : state.freq === 'weekly' ? 'week(s)' : 'month(s)' }}</span>
    </div>

    <!-- Weekly day-of-week picker -->
    <div v-if="state.freq === 'weekly'" class="flex items-start gap-2 flex-wrap">
      <label class="text-[--fg-3] w-20 flex-shrink-0">On</label>
      <div class="flex gap-1 flex-wrap">
        <button
          v-for="(d, i) in DOW_CODES"
          :key="d"
          type="button"
          :data-testid="`rrule-dow-${d}`"
          class="px-1.5 py-0.5 rounded text-[11px] border transition-colors"
          :class="state.byday.includes(d) ? 'bg-[--accent] text-[--accent-fg] border-[--accent]' : 'text-[--fg-4] border-[--border-soft] hover:border-[--border-1]'"
          @click="toggleDow(d)"
        >{{ DOW_LABELS[i] }}</button>
      </div>
    </div>

    <!-- Monthly mode picker -->
    <div v-if="state.freq === 'monthly'" class="flex flex-col gap-1 pl-22">
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="radio" v-model="state.monthlyMode" value="date" @change="onMonthlyModeChange" />
        <span class="text-[--fg-3]">Same date each month</span>
      </label>
      <label class="flex items-center gap-2 cursor-pointer flex-wrap">
        <input type="radio" v-model="state.monthlyMode" value="byday" @change="onMonthlyModeChange" />
        <span class="text-[--fg-3]">On the</span>
        <select
          v-if="state.monthlyMode === 'byday'"
          data-testid="rrule-nth-weekday"
          class="bg-[--bg-elev-1] border border-[--border-1] rounded px-1 py-0.5 text-[--fg-1] text-xs"
          :value="state.nthWeekday"
          @change="onNthWeekdayChange"
        >
          <option value="1">1st</option>
          <option value="2">2nd</option>
          <option value="3">3rd</option>
          <option value="4">4th</option>
        </select>
        <select
          v-if="state.monthlyMode === 'byday'"
          data-testid="rrule-monthly-dow"
          class="bg-[--bg-elev-1] border border-[--border-1] rounded px-1 py-0.5 text-[--fg-1] text-xs"
          :value="state.byday[0] ?? 'MO'"
          @change="onMonthlyDowChange"
        >
          <option v-for="(d, i) in DOW_CODES" :key="d" :value="d">{{ DOW_LABELS[i] }}</option>
        </select>
      </label>
    </div>

    <!-- End condition -->
    <div v-if="state.freq !== 'none' && state.freq !== 'custom'" class="flex items-center gap-2 flex-wrap">
      <label class="text-[--fg-3] w-20 flex-shrink-0">Ends</label>
      <select
        class="bg-[--bg-elev-1] border border-[--border-1] rounded px-2 py-1 text-[--fg-1] text-xs"
        v-model="state.endMode"
        @change="emitValue"
      >
        <option value="never">Never</option>
        <option value="count">After N occurrences</option>
        <option value="until">On date</option>
      </select>
      <input
        v-if="state.endMode === 'count'"
        type="number" min="1" max="999"
        data-testid="rrule-count"
        class="w-16 bg-[--bg-elev-1] border border-[--border-soft] rounded px-2 py-1 text-[--fg-1] text-xs"
        :value="state.count"
        @change="onCountChange"
      />
      <input
        v-if="state.endMode === 'until'"
        type="date"
        data-testid="rrule-until"
        class="bg-[--bg-elev-1] border border-[--border-soft] rounded px-2 py-1 text-[--fg-1] text-xs"
        :value="state.until"
        @change="onUntilChange"
      />
    </div>

    <!-- Custom RRULE fallback -->
    <input
      v-if="state.freq === 'custom'"
      data-testid="rrule-custom-input"
      type="text"
      :value="customRrule"
      placeholder="e.g. FREQ=WEEKLY;BYDAY=MO,WE"
      @change="onCustomInput"
      class="bg-[--bg-elev-1] text-[--fg-1] text-sm rounded px-2 py-1 border border-[--border-1] outline-none focus:border-[--border-2] font-mono w-full"
    />
  </div>
</template>
