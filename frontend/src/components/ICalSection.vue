<script setup lang="ts">
import { ref, computed } from 'vue'
import { useICalStore } from '../stores/ical'

const store = useICalStore()

// ── Mode tabs ────────────────────────────────────────────────────────────────
type Mode = 'file' | 'url'
const mode = ref<Mode>('file')

function setMode(m: Mode) {
  mode.value = m
  selectedFile.value = null
  feedUrl.value = ''
  dropError.value = null
  store.clearResult()
}

// ── Options ──────────────────────────────────────────────────────────────────
const skipAllDay = ref(false)

// ── File mode ────────────────────────────────────────────────────────────────
const selectedFile = ref<File | null>(null)
const isDragOver = ref(false)
const dropError = ref<string | null>(null)

const fileInput = ref<HTMLInputElement | null>(null)

function onFileChange(event: Event) {
  dropError.value = null
  const files = (event.target as HTMLInputElement).files
  if (files && files.length > 0) {
    const file = files[0]
    if (!file.name.toLowerCase().endsWith('.ics')) {
      dropError.value = 'Please select a .ics calendar file.'
      selectedFile.value = null
      return
    }
    selectedFile.value = file
    store.clearResult()
  }
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false
  dropError.value = null
  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return
  const file = files[0]
  if (!file.name.toLowerCase().endsWith('.ics')) {
    dropError.value = 'Only .ics calendar files are accepted.'
    selectedFile.value = null
    return
  }
  selectedFile.value = file
  store.clearResult()
}

// ── URL mode ─────────────────────────────────────────────────────────────────
const feedUrl = ref('')

// ── Import action ─────────────────────────────────────────────────────────────
const canImport = computed(() => {
  if (store.importing) return false
  if (mode.value === 'file') return selectedFile.value !== null
  return feedUrl.value.trim().length > 0
})

async function runImport() {
  if (!canImport.value) return
  if (mode.value === 'file' && selectedFile.value) {
    await store.importFile(selectedFile.value, skipAllDay.value)
  } else if (mode.value === 'url') {
    await store.importUrl(feedUrl.value.trim(), skipAllDay.value)
  }
}

// ── Result summary ─────────────────────────────────────────────────────────
// Auto-expand errors so they are immediately visible; user can collapse.
const showErrors = ref(true)
</script>

<template>
  <section class="mb-8">
    <h2 class="text-sm font-semibold text-[--fg-3] uppercase tracking-wider mb-3">iCal / ICS Import</h2>
    <div class="bg-[--bg-elev-1] rounded-xl p-4 space-y-4">

      <!-- Mode tabs -->
      <div class="flex gap-1 bg-[--bg-elev-2] rounded-lg p-0.5 w-fit">
        <button
          data-testid="ical-tab-file"
          @click="setMode('file')"
          :class="mode === 'file'
            ? 'bg-[--bg-elev-1] text-[--fg-1] shadow-sm'
            : 'text-[--fg-4] hover:text-[--fg-2]'"
          class="text-sm font-medium rounded-md px-3 py-1 transition-colors"
        >
          File
        </button>
        <button
          data-testid="ical-tab-url"
          @click="setMode('url')"
          :class="mode === 'url'
            ? 'bg-[--bg-elev-1] text-[--fg-1] shadow-sm'
            : 'text-[--fg-4] hover:text-[--fg-2]'"
          class="text-sm font-medium rounded-md px-3 py-1 transition-colors"
        >
          URL
        </button>
      </div>

      <!-- File mode: drag-drop zone -->
      <template v-if="mode === 'file'">
        <div
          data-testid="ical-drop-zone"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
          @click="fileInput?.click()"
          :class="isDragOver
            ? 'border-[--accent] bg-[--accent-veil]'
            : 'border-[--border-1] hover:border-[--border-2]'"
          class="border-2 border-dashed rounded-xl p-6 flex flex-col items-center gap-2 cursor-pointer transition-colors text-center"
        >
          <!-- Calendar icon -->
          <svg class="w-8 h-8 text-[--fg-4]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
          </svg>
          <div>
            <p class="text-sm text-[--fg-2] font-medium">
              {{ selectedFile ? selectedFile.name : 'Drop a .ics file here' }}
            </p>
            <p class="text-xs text-[--fg-4] mt-0.5">or click to browse</p>
          </div>
        </div>

        <!-- Hidden file input -->
        <input
          ref="fileInput"
          data-testid="ical-file-input"
          type="file"
          accept=".ics"
          class="hidden"
          @change="onFileChange"
        />

        <!-- Drop validation error -->
        <p v-if="dropError" class="text-xs text-[--status-block-fg]">{{ dropError }}</p>
      </template>

      <!-- URL mode: feed input -->
      <template v-else>
        <div class="space-y-1">
          <label class="text-xs text-[--fg-4]">Subscription feed URL</label>
          <input
            v-model="feedUrl"
            data-testid="ical-url-input"
            type="url"
            placeholder="webcal://… or https://…"
            class="w-full bg-[--bg-elev-2] text-[--fg-1] rounded-lg px-3 py-2 text-sm border border-[--border-1] focus:outline-none focus:border-[--accent] placeholder:text-[--fg-5]"
          />
          <p class="text-xs text-[--fg-5]">
            One-shot import. Auto-sync will be available in a future update.
          </p>
        </div>
      </template>

      <!-- Skip all-day checkbox -->
      <label class="flex items-center gap-2 cursor-pointer select-none">
        <input
          v-model="skipAllDay"
          data-testid="ical-skip-all-day"
          type="checkbox"
          class="w-4 h-4 rounded border-[--border-1] text-[--accent] accent-[--accent]"
        />
        <span class="text-sm text-[--fg-2]">Skip all-day events</span>
      </label>

      <!-- Import button -->
      <button
        data-testid="ical-import-btn"
        :disabled="!canImport"
        @click="runImport"
        class="w-full bg-[--accent] hover:opacity-90 disabled:opacity-40 text-[--accent-fg] text-sm font-medium rounded-lg px-4 py-2 transition-colors"
      >
        {{ store.importing ? 'Importing…' : 'Import' }}
      </button>

      <!-- Result summary -->
      <div v-if="store.lastResult" class="rounded-lg bg-[--status-done-bg] border border-[--status-done-fg]/20 px-3 py-2.5 space-y-1.5">
        <p class="text-sm text-[--status-done-fg] font-medium">
          ✓ {{ store.lastResult.imported }} imported
          · {{ store.lastResult.updated }} updated
          · {{ store.lastResult.skipped }} skipped
        </p>
        <p v-if="store.lastResult.warning" class="text-xs text-[--fg-3]">
          ⚠ {{ store.lastResult.warning }}
        </p>

        <!-- Per-event errors -->
        <template v-if="store.lastResult.errors.length > 0">
          <button
            @click="showErrors = !showErrors"
            class="text-xs text-[--fg-3] hover:text-[--fg-1] underline"
          >
            {{ showErrors ? 'Hide' : 'Show' }} {{ store.lastResult.errors.length }} error(s)
          </button>
          <ul v-if="showErrors" class="space-y-0.5 mt-1">
            <li
              v-for="err in store.lastResult.errors"
              :key="err.uid"
              class="text-xs text-[--status-block-fg]"
            >
              {{ err.uid }}: {{ err.error }}
            </li>
          </ul>
        </template>
      </div>

      <!-- Error message -->
      <p
        v-if="store.lastError"
        data-testid="ical-error"
        class="text-sm text-[--status-block-fg]"
      >
        {{ store.lastError }}
      </p>

      <!-- Info text -->
      <p v-if="!store.lastResult && !store.lastError" class="text-xs text-[--fg-4]">
        Import calendar events from an ICS file or a subscription feed URL.
      </p>
    </div>
  </section>
</template>
