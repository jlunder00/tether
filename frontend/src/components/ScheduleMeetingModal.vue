<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useMeetingsStore } from '../stores/meetings'

const props = defineProps<{
  visible: boolean
  /** Username (display handle) of the connection we're scheduling with */
  targetUsername: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'sent'): void
}>()

const store = useMeetingsStore()

const durationMinutes = ref(30)
const context = ref('')
/** Set of ISO strings the user has toggled on */
const selectedSlots = ref<Set<string>>(new Set())

const DURATIONS = [
  { label: '15 min', value: 15 },
  { label: '30 min', value: 30 },
  { label: '60 min', value: 60 },
  { label: '90 min', value: 90 },
]

/** Pre-populate next 5 weekdays × 3 times (9am, 1pm, 4pm) in local time */
function buildDefaultSlots(): Array<{ iso: string; label: string }> {
  const slots: Array<{ iso: string; label: string }> = []
  const hours = [9, 13, 16]
  const date = new Date()
  date.setHours(0, 0, 0, 0)
  let weekdaysFound = 0
  while (weekdaysFound < 5) {
    date.setDate(date.getDate() + 1)
    const dow = date.getDay()
    if (dow === 0 || dow === 6) continue // skip weekends
    weekdaysFound++
    for (const h of hours) {
      const d = new Date(date)
      d.setHours(h, 0, 0, 0)
      const label = d.toLocaleString(undefined, {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      })
      // Use UTC ISO string so the backend gets unambiguous times
      slots.push({ iso: d.toISOString(), label })
    }
  }
  return slots
}

const defaultSlots = ref(buildDefaultSlots())

// Re-generate and pre-select all slots whenever the modal opens
watch(() => props.visible, (open) => {
  if (open) {
    durationMinutes.value = 30
    context.value = ''
    store.error = null
    defaultSlots.value = buildDefaultSlots()
    selectedSlots.value = new Set(defaultSlots.value.map(s => s.iso))
  }
})

function toggleSlot(iso: string) {
  const next = new Set(selectedSlots.value)
  if (next.has(iso)) {
    next.delete(iso)
  } else {
    next.add(iso)
  }
  selectedSlots.value = next
}

const canSubmit = computed(() => selectedSlots.value.size > 0 && !store.loading)

async function handleSubmit() {
  if (!canSubmit.value) return
  await store.requestMeeting({
    target_usernames: [props.targetUsername],
    duration_minutes: durationMinutes.value,
    slots: Array.from(selectedSlots.value),
    context: context.value.trim() || undefined,
  })
  if (!store.error) {
    emit('sent')
    emit('close')
  }
}

function onCancel() {
  store.error = null
  emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') onCancel()
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-[200] flex items-center justify-center bg-black/60"
      data-testid="schedule-meeting-modal"
      @click.self="onCancel"
      @keydown="onKeydown"
      tabindex="0"
    >
      <div class="w-96 bg-[--bg-elev-1] border border-[--border-1] rounded-xl shadow-xl p-5 space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 class="text-sm font-semibold text-[--fg-1]">
          Schedule meeting with
          <span class="text-[--accent]">{{ targetUsername }}</span>
        </h3>

        <!-- Error -->
        <div
          v-if="store.error"
          class="bg-[--status-block-bg] border border-[--border-1] rounded-lg p-3 text-sm text-[--status-block-fg]"
          data-testid="schedule-modal-error"
        >
          {{ store.error }}
        </div>

        <!-- Duration -->
        <div>
          <p class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-2">Duration</p>
          <div class="flex gap-2">
            <button
              v-for="d in DURATIONS"
              :key="d.value"
              :class="durationMinutes === d.value
                ? 'bg-[--accent] text-[--accent-fg]'
                : 'bg-[--bg-elev-2] text-[--fg-2] hover:bg-[--bg-elev-3]'"
              class="text-xs px-3 py-1.5 rounded-lg transition-colors"
              :data-testid="`duration-${d.value}`"
              @click="durationMinutes = d.value"
            >
              {{ d.label }}
            </button>
          </div>
        </div>

        <!-- Proposed times -->
        <div>
          <p class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-2">
            Proposed times
            <span class="normal-case tracking-normal font-normal text-[--fg-5] ml-1">({{ selectedSlots.size }} selected)</span>
          </p>
          <p class="text-xs text-[--fg-5] mb-2">Uncheck any slots you can't make. The other person will see your available times.</p>
          <ul class="space-y-1 max-h-52 overflow-y-auto pr-1">
            <li
              v-for="slot in defaultSlots"
              :key="slot.iso"
              class="flex items-center gap-2 py-0.5"
            >
              <input
                type="checkbox"
                :checked="selectedSlots.has(slot.iso)"
                :id="`slot-${slot.iso}`"
                @change="toggleSlot(slot.iso)"
                class="rounded accent-[--accent] cursor-pointer"
                :data-testid="`slot-checkbox-${slot.iso}`"
              />
              <label
                :for="`slot-${slot.iso}`"
                class="text-sm text-[--fg-2] cursor-pointer select-none"
              >
                {{ slot.label }}
              </label>
            </li>
          </ul>
          <p
            v-if="selectedSlots.size === 0"
            class="text-xs text-[--status-block-fg] mt-1"
            data-testid="no-slots-warning"
          >
            Select at least one time slot.
          </p>
        </div>

        <!-- Context / note -->
        <div>
          <label class="text-xs font-medium text-[--fg-4] uppercase tracking-wide mb-1 block" for="meeting-context">
            Note <span class="normal-case font-normal tracking-normal text-[--fg-5]">(optional)</span>
          </label>
          <textarea
            id="meeting-context"
            v-model="context"
            rows="2"
            placeholder="e.g. Weekly sync, project review…"
            class="w-full bg-[--bg-elev-2] text-[--fg-1] border border-[--border-1] rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
            data-testid="meeting-context-input"
          />
        </div>

        <!-- Actions -->
        <div class="flex justify-end gap-2 pt-1">
          <button
            class="px-3 py-1.5 text-xs rounded-lg text-[--fg-3] hover:text-[--fg-1] hover:bg-[--bg-elev-2] transition-colors"
            data-testid="schedule-modal-cancel"
            @click="onCancel"
          >
            Cancel
          </button>
          <button
            :disabled="!canSubmit"
            class="px-4 py-1.5 text-xs rounded-lg bg-[--accent] text-[--accent-fg] hover:opacity-90 disabled:opacity-50 transition-opacity"
            data-testid="schedule-modal-submit"
            @click="handleSubmit"
          >
            {{ store.loading ? 'Sending…' : 'Send request' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
