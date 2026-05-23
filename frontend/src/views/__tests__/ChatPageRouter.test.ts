import { describe, it, expect, vi } from 'vitest'

// We test the router config by importing it directly — but it imports vue-router and
// useAuthStore which need mocking.

vi.mock('vue-router', async () => {
  const actual = await vi.importActual<typeof import('vue-router')>('vue-router')
  return {
    ...actual,
    createRouter: vi.fn((opts) => ({
      ...opts,
      _mockRouter: true,
      routes: opts.routes,
      beforeEach: vi.fn(),
    })),
    createWebHistory: vi.fn(() => ({})),
  }
})

vi.mock('../../stores/auth', () => ({
  useAuthStore: vi.fn(),
}))

describe('router — /context legacy redirect', () => {
  it('has a /context redirect entry pointing at /chat', async () => {
    const { default: router } = await import('../../router')
    const routes = (router as any).routes as Array<{ path: string; redirect?: any }>
    const contextRoute = routes.find(r => r.path === '/context')
    expect(contextRoute).toBeDefined()
    expect(contextRoute?.redirect).toBeDefined()
    // Function-form redirect (so query params can be preserved)
    expect(typeof contextRoute?.redirect).toBe('function')
  })

  it('redirect function preserves query params and hash', async () => {
    const { default: router } = await import('../../router')
    const routes = (router as any).routes as Array<{ path: string; redirect?: any }>
    const contextRoute = routes.find(r => r.path === '/context')
    const redirectFn = contextRoute?.redirect as (to: any) => any
    const result = redirectFn({ query: { panels: 'task:abc' }, hash: '#sec' })
    expect(result.path).toBe('/chat')
    expect(result.query).toEqual({ panels: 'task:abc' })
    expect(result.hash).toBe('#sec')
  })
})

describe('router — /chat child routes', () => {
  it('has chat-node child route at node/:nodeId with props: true', async () => {
    vi.resetModules()
    const { default: router } = await import('../../router')
    const routes = (router as any).routes as Array<{ path: string; name?: string; children?: any[] }>
    const chatRoute = routes.find(r => r.path === '/chat')
    expect(chatRoute).toBeDefined()
    const chatNode = chatRoute?.children?.find((c: any) => c.name === 'chat-node')
    expect(chatNode).toBeDefined()
    expect(chatNode?.path).toBe('node/:nodeId')
    expect(chatNode?.props).toBe(true)
  })

  it('has chat-conversation child route at conversation/:convId with props: true', async () => {
    vi.resetModules()
    const { default: router } = await import('../../router')
    const routes = (router as any).routes as Array<{ path: string; name?: string; children?: any[] }>
    const chatRoute = routes.find(r => r.path === '/chat')
    const chatConv = chatRoute?.children?.find((c: any) => c.name === 'chat-conversation')
    expect(chatConv).toBeDefined()
    expect(chatConv?.path).toBe('conversation/:convId')
    expect(chatConv?.props).toBe(true)
  })

  it('/chat route has a name of "chat"', async () => {
    vi.resetModules()
    const { default: router } = await import('../../router')
    const routes = (router as any).routes as Array<{ path: string; name?: string }>
    const chatRoute = routes.find(r => r.path === '/chat')
    expect(chatRoute?.name).toBe('chat')
  })
})
