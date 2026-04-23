import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock vue-router before importing the composable
const replaceMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useRoute: () => ({ query: {} }),
}))

import { useSlideOver, resetSlideOverStack } from '../useSlideOver'

describe('useSlideOver composable', () => {
  beforeEach(() => {
    replaceMock.mockClear()
    resetSlideOverStack()
  })

  it('starts with an empty stack', () => {
    const { stack } = useSlideOver()
    expect(stack.value).toHaveLength(0)
  })

  it('push adds a panel to the stack', () => {
    const { push, stack } = useSlideOver()
    push({ kind: 'task', entityId: 'abc' })
    expect(stack.value).toHaveLength(1)
    expect(stack.value[0].kind).toBe('task')
    expect(stack.value[0].entityId).toBe('abc')
    expect(stack.value[0].id).toBeTruthy()
  })

  it('pop removes the top panel', () => {
    const { push, pop, stack } = useSlideOver()
    push({ kind: 'task', entityId: 'abc' })
    push({ kind: 'milestone', entityId: 'xyz' })
    pop()
    expect(stack.value).toHaveLength(1)
    expect(stack.value[0].entityId).toBe('abc')
  })

  it('close empties the stack', () => {
    const { push, close, stack } = useSlideOver()
    push({ kind: 'task', entityId: 'a' })
    push({ kind: 'task', entityId: 'b' })
    close()
    expect(stack.value).toHaveLength(0)
  })

  it('push syncs to URL via router.replace', () => {
    const { push } = useSlideOver()
    push({ kind: 'task', entityId: 'abc' })
    expect(replaceMock).toHaveBeenCalledOnce()
    const call = replaceMock.mock.calls[0][0]
    expect(call.query.panels).toContain('task:abc')
  })

  it('pop syncs to URL after removing top panel', () => {
    const { push, pop } = useSlideOver()
    push({ kind: 'task', entityId: 'abc' })
    push({ kind: 'milestone', entityId: 'xyz' })
    replaceMock.mockClear()
    pop()
    expect(replaceMock).toHaveBeenCalledOnce()
    const call = replaceMock.mock.calls[0][0]
    expect(call.query.panels).toBe('task:abc')
    expect(call.query.panels).not.toContain('milestone')
  })

  it('close syncs URL with empty panels param', () => {
    const { push, close } = useSlideOver()
    push({ kind: 'task', entityId: 'abc' })
    replaceMock.mockClear()
    close()
    const call = replaceMock.mock.calls[0][0]
    expect(call.query.panels).toBeUndefined()
  })
})
