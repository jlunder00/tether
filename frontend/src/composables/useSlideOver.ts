import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'

export interface Panel {
  id: string
  kind: 'task' | 'milestone' | 'context' | 'event'
  entityId: string
}

// Module-level reactive state so the stack is shared across all callers.
// resetSlideOverStack() is exported for tests only.
const stack = ref<Panel[]>([])

export function resetSlideOverStack() {
  stack.value = []
}

function encodeStack(panels: Panel[]): string | undefined {
  if (!panels.length) return undefined
  return panels.map(p => `${p.kind}:${p.entityId}`).join(',')
}

function genId(): string {
  return crypto.randomUUID?.() ?? (Math.random().toString(36).slice(2) + Date.now().toString(36))
}

function decodeStack(param: string): Panel[] {
  const result: Panel[] = []
  for (const segment of param.split(',').filter(Boolean)) {
    const colon = segment.indexOf(':')
    if (colon === -1) continue
    const kind = segment.slice(0, colon) as Panel['kind']
    const entityId = segment.slice(colon + 1)
    result.push({ id: genId(), kind, entityId })
  }
  return result
}

export function useSlideOver() {
  const router = useRouter()
  const route = useRoute()

  function syncToUrl() {
    const encoded = encodeStack(stack.value)
    router.replace({
      query: {
        ...route.query,
        panels: encoded,
      },
    })
  }

  function push(panel: Omit<Panel, 'id'>) {
    stack.value.push({ ...panel, id: genId() })
    syncToUrl()
  }

  function pop() {
    stack.value.pop()
    syncToUrl()
  }

  function close() {
    stack.value = []
    syncToUrl()
  }

  /** Restore stack from URL query param (call on app mount / route change). */
  function restoreFromUrl() {
    const param = route.query.panels
    if (typeof param === 'string' && param) {
      stack.value = decodeStack(param)
    }
  }

  return { stack, push, pop, close, restoreFromUrl }
}
