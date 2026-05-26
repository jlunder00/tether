<script setup lang="ts">
import { ref, watch } from 'vue'
import { useContextStore } from '../../stores/context'
import type { SectionFileInfo } from '../../stores/context'

const props = defineProps<{ nodeId: string | null }>()
const emit  = defineEmits<{ collapse: [] }>()

const ctxStore = useContextStore()

const activeTab    = ref<'details' | 'files'>('details')
const contextBody  = ref('')
const savedAt      = ref<number | null>(null)   // timestamp of last save (for indicator)
const files        = ref<SectionFileInfo[]>([])
let   saveTimer: ReturnType<typeof setTimeout> | null = null

// ── Load section on nodeId change ────────────────────────
watch(() => props.nodeId, async (id) => {
  if (!id) { contextBody.value = ''; files.value = []; return }
  const section = await ctxStore.fetchSection(id, 'details')
  contextBody.value = section?.body ?? ''
  files.value = await ctxStore.fetchSectionFiles(id, 'files').catch(() => [])
}, { immediate: true })

// ── Autosave ─────────────────────────────────────────────
function onContextInput() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(saveContext, 800)
}

async function onContextBlur() {
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }
  await saveContext()
}

async function saveContext() {
  if (!props.nodeId) return
  await ctxStore.saveSection(props.nodeId, 'details', contextBody.value)
  const ts = Date.now()
  savedAt.value = ts
  // Auto-fade the "Saved" indicator after 2 seconds.
  // Guard against race: only clear if savedAt hasn't been updated since.
  setTimeout(() => { if (savedAt.value === ts) savedAt.value = null }, 2000)
}

// ── File upload via drop ──────────────────────────────────
const dropActive = ref(false)

function onDropZoneDragover(e: DragEvent) { e.preventDefault(); dropActive.value = true }
function onDropZoneDragleave()            { dropActive.value = false }
// TODO: File upload implementation depends on backend API — wire to upload endpoint when ready
async function onDrop(e: DragEvent) {
  e.preventDefault(); dropActive.value = false
  console.log('TODO: file upload not yet wired — backend endpoint needed', e.dataTransfer?.files)
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}
</script>

<template>
  <div class="details-pane">

    <!-- ── Tab bar ── -->
    <div class="details-tabs">
      <button
        class="details-tab"
        :class="{ 'is-active': activeTab === 'details' }"
        @click="activeTab = 'details'"
      >Details</button>
      <button
        class="details-tab"
        :class="{ 'is-active': activeTab === 'files' }"
        @click="activeTab = 'files'"
      >Files</button>
      <button
        data-testid="collapse-btn"
        class="details-collapse"
        title="Collapse"
        @click="emit('collapse')"
      >›</button>
    </div>

    <!-- ── Details tab ── -->
    <div v-if="activeTab === 'details'" class="details-body">
      <div class="det-sec">
        <span class="det-sec__label">Context</span>
        <textarea
          v-model="contextBody"
          data-testid="context-textarea"
          class="det-sec__area"
          placeholder="Describe what this folder is about. Injected into every chat here."
          @input="onContextInput"
          @blur="onContextBlur"
        />
        <div v-if="savedAt" class="det-sec__saved">Saved</div>
      </div>

      <div class="det-add">
        <span class="det-add__line" />
        + add section
        <span class="det-add__line" />
      </div>
    </div>

    <!-- ── Files tab ── -->
    <div v-else class="details-body">
      <div class="det-sec">
        <span class="det-sec__label">Attached files</span>

        <div v-if="files.length > 0" class="det-filelist">
          <div v-for="f in files" :key="f.name" class="det-fileitem">
            <svg class="det-fileitem__ico" width="13" height="13" viewBox="0 0 16 16"
                 fill="none" stroke="currentColor" stroke-width="1.5"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M4 1h6l4 4v10H4V1z"/><path d="M10 1v4h4"/>
            </svg>
            <span class="det-fileitem__name">{{ f.name }}</span>
            <span class="det-fileitem__size">{{ formatSize(f.size) }}</span>
          </div>
        </div>

        <div
          class="det-dropzone"
          :class="{ 'det-dropzone--active': dropActive }"
          @dragover="onDropZoneDragover"
          @dragleave="onDropZoneDragleave"
          @drop="onDrop"
        >
          Drop files here · or click to browse
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.details-pane {
  width: 320px; flex-shrink: 0;
  border-left: 1px solid var(--border-1);
  display: flex; flex-direction: column;
  background: var(--bg-canvas); overflow: hidden;
}

/* Tab bar */
.details-tabs {
  display: flex; flex-shrink: 0;
  border-bottom: 1px solid var(--border-1);
  align-items: center;
}
.details-tab {
  padding: 10px 16px; font-size: 12px;
  color: var(--fg-4); cursor: pointer;
  border: none; background: transparent;
  border-bottom: 2px solid transparent;
  transition: color 150ms; font-family: var(--font-sans);
}
.details-tab.is-active { color: var(--fg-1); border-bottom-color: var(--accent); }
.details-tab:hover:not(.is-active) { color: var(--fg-2); }
.details-collapse {
  margin-left: auto; margin-right: 8px;
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent; cursor: pointer;
  font-size: 13px; color: var(--fg-5); border-radius: var(--radius-sharp);
  transition: color 150ms, background 150ms;
}
.details-collapse:hover { color: var(--fg-2); background: var(--bg-elev-3); }

/* Body */
.details-body { flex: 1; overflow-y: auto; padding: 18px 18px 40px; }

.det-sec { margin-bottom: 22px; }
.det-sec__label {
  display: block; font-family: var(--font-mono); font-size: 9.5px;
  letter-spacing: 0.14em; text-transform: uppercase;
  color: var(--fg-5); margin-bottom: 8px;
}
.det-sec__area {
  width: 100%; min-height: 80px;
  background: transparent; border: none; outline: none;
  resize: none; font-family: var(--font-sans); font-size: 12.5px;
  line-height: 1.65; color: var(--fg-2);
  padding: 0; box-sizing: border-box;
  transition: background 150ms, padding 150ms;
}
.det-sec__area::placeholder { color: var(--fg-6); }
.det-sec__area:focus {
  background: var(--bg-elev-1); padding: 8px 10px;
  border-radius: var(--radius-sharp);
  box-shadow: inset 0 0 0 1px var(--border-1);
}
.det-sec__saved {
  margin-top: 4px; font-family: var(--font-mono); font-size: 10px; color: var(--fg-5);
  animation: fadeout 2s forwards;
}
@keyframes fadeout { 0% { opacity: 1; } 70% { opacity: 1; } 100% { opacity: 0; } }

.det-add {
  display: flex; align-items: center; gap: 8px;
  font-family: var(--font-mono); font-size: 11px;
  color: var(--fg-5); cursor: pointer; opacity: 0.6;
  padding: 4px 0; transition: opacity 150ms, color 150ms;
}
.det-add:hover { opacity: 1; color: var(--fg-2); }
.det-add__line { flex: 1; height: 1px; background: var(--border-soft); }

/* Files */
.det-filelist { display: flex; flex-direction: column; gap: 4px; margin-bottom: 14px; }
.det-fileitem {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 0; font-size: 12px; color: var(--fg-3);
}
.det-fileitem__ico { color: var(--fg-5); flex-shrink: 0; }
.det-fileitem__name { flex: 1; }
.det-fileitem__size { font-family: var(--font-mono); font-size: 10.5px; color: var(--fg-5); }
.det-dropzone {
  border: 1px dashed var(--border-1); border-radius: var(--radius-sharp);
  padding: 20px; text-align: center;
  font-family: var(--font-mono); font-size: 11.5px; color: var(--fg-5);
  cursor: pointer; transition: border-color 150ms, background 150ms, color 150ms;
}
.det-dropzone:hover,
.det-dropzone--active {
  border-color: var(--accent-soft); background: var(--accent-veil); color: var(--accent);
}
</style>
