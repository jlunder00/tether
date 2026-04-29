import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// Mock the auth store — hoisted to top level by vitest
vi.mock('../../stores/auth', () => ({
  useAuthStore: () => ({ user: null }),
}))

describe('useTheme', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Reset document attributes
    delete document.documentElement.dataset.theme
    delete document.documentElement.dataset.mode
    delete document.documentElement.dataset.typeVoice
    delete document.documentElement.dataset.themeSwap
    localStorage.clear()
    vi.resetModules()
  })

  it('applyTheme sets data-theme on documentElement', async () => {
    const { useTheme } = await import('../useTheme')
    const { applyTheme } = useTheme()
    applyTheme('tether')
    expect(document.documentElement.dataset.theme).toBe('tether')
  })

  it('applyTheme persists to localStorage', async () => {
    const { useTheme } = await import('../useTheme')
    const { applyTheme } = useTheme()
    applyTheme('horizon')
    expect(localStorage.getItem('tether-theme')).toBe('horizon')
  })

  it('applyTheme sets data-type-voice based on theme', async () => {
    const { useTheme } = await import('../useTheme')
    const { applyTheme } = useTheme()
    applyTheme('horizon')
    expect(document.documentElement.dataset.typeVoice).toBe('editorial')
  })

  it('applyTheme does not apply locked themes for free user', async () => {
    const { useTheme } = await import('../useTheme')
    const { applyTheme } = useTheme()
    // Start on tether
    applyTheme('tether')
    expect(document.documentElement.dataset.theme).toBe('tether')
    // Try to switch to paid-oss theme (should be blocked for free user)
    applyTheme('terminal')
    // Should remain on tether
    expect(document.documentElement.dataset.theme).toBe('tether')
  })

  it('isThemeUnlocked returns true for free tier themes', async () => {
    const { useTheme, THEMES } = await import('../useTheme')
    const { isThemeUnlocked } = useTheme()
    const freeTheme = THEMES.find(t => t.id === 'tether')!
    expect(isThemeUnlocked(freeTheme)).toBe(true)
  })

  it('isThemeUnlocked returns false for paid-oss themes when not paid', async () => {
    const { useTheme, THEMES } = await import('../useTheme')
    const { isThemeUnlocked } = useTheme()
    const paidOssTheme = THEMES.find(t => t.id === 'terminal')!
    expect(isThemeUnlocked(paidOssTheme)).toBe(false)
  })

  it('isThemeUnlocked returns true for paid-oss themes when user is_paid', async () => {
    vi.doMock('../../stores/auth', () => ({
      useAuthStore: () => ({ user: { user_id: '1', username: 'alice', is_admin: false, is_paid: true } }),
    }))
    const { useTheme, THEMES } = await import('../useTheme')
    const { isThemeUnlocked } = useTheme()
    const paidOssTheme = THEMES.find(t => t.id === 'terminal')!
    expect(isThemeUnlocked(paidOssTheme)).toBe(true)
  })

  it('setMode updates data-mode and localStorage', async () => {
    const { useTheme } = await import('../useTheme')
    const { setMode } = useTheme()
    setMode('light')
    expect(document.documentElement.dataset.mode).toBe('light')
    expect(localStorage.getItem('tether-mode')).toBe('light')

    setMode('dark')
    expect(document.documentElement.dataset.mode).toBe('dark')
    expect(localStorage.getItem('tether-mode')).toBe('dark')
  })

  it('THEMES list has expected themes', async () => {
    const { THEMES } = await import('../useTheme')
    const ids = THEMES.map(t => t.id)
    expect(ids).toContain('tether')
    expect(ids).toContain('horizon')
    expect(ids).toContain('contrast')
    expect(ids).toContain('terminal')
    expect(ids).toContain('solstice')
    expect(ids).toContain('dracula')
    expect(ids).toContain('paper')
  })

  it('previewTheme sets data-theme even for locked (paid-oss) theme', async () => {
    const { useTheme } = await import('../useTheme')
    const { previewTheme } = useTheme()
    previewTheme('terminal')
    expect(document.documentElement.dataset.theme).toBe('terminal')
  })

  it('previewTheme does NOT persist to localStorage', async () => {
    const { useTheme } = await import('../useTheme')
    const { previewTheme } = useTheme()
    previewTheme('terminal')
    expect(localStorage.getItem('tether-theme')).toBeNull()
  })

  it('previewTheme sets data-type-voice without persistence', async () => {
    const { useTheme } = await import('../useTheme')
    const { previewTheme } = useTheme()
    previewTheme('terminal')
    expect(document.documentElement.dataset.typeVoice).toBe('terminal')
  })
})

describe('useTheme - community edition', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    delete document.documentElement.dataset.theme
    delete document.documentElement.dataset.mode
    delete document.documentElement.dataset.typeVoice
    localStorage.clear()
    vi.resetModules()
  })

  it('isThemeUnlocked returns true for paid-oss when community edition', async () => {
    // Set the global before module import to simulate community edition build
    ;(globalThis as any).__TETHER_EDITION__ = 'community'
    const { useTheme, THEMES } = await import('../useTheme')
    const { isThemeUnlocked } = useTheme()
    const terminalTheme = THEMES.find(t => t.id === 'terminal')!
    expect(isThemeUnlocked(terminalTheme)).toBe(true)
    delete (globalThis as any).__TETHER_EDITION__
  })
})
