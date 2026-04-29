import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'

describe('loadPremiumThemes', () => {
  const fakeToken = 'fake-token'

  beforeEach(() => {
    // Remove any existing premium-themes style element
    const el = document.getElementById('premium-themes')
    if (el) el.remove()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('injects a <style id="premium-themes"> element when API responds ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          themes: [
            { id: 'terminal', name: 'Terminal', css: ':root[data-theme="terminal"] { --canvas: #0A0E0A; }' },
          ],
        }),
      } as Response),
    )

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    await loadPremiumThemes(fakeToken)

    const el = document.getElementById('premium-themes')
    expect(el).not.toBeNull()
    expect(el?.tagName).toBe('STYLE')
    expect(el?.textContent).toContain('--canvas: #0A0E0A')
  })

  it('replaces existing <style id="premium-themes"> content on second call', async () => {
    const existing = document.createElement('style')
    existing.id = 'premium-themes'
    existing.textContent = 'old-css {}'
    document.head.appendChild(existing)

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          themes: [{ id: 'dracula', name: 'Dracula', css: '.new-css {}' }],
        }),
      } as Response),
    )

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    await loadPremiumThemes(fakeToken)

    const all = document.querySelectorAll('#premium-themes')
    expect(all).toHaveLength(1)
    expect(all[0].textContent).toBe('.new-css {}')
  })

  it('does nothing when API returns non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({}),
      } as Response),
    )

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    await loadPremiumThemes(fakeToken)

    expect(document.getElementById('premium-themes')).toBeNull()
  })

  it('sends Authorization header with bearer token when token is provided', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ themes: [] }),
    } as Response)
    vi.stubGlobal('fetch', mockFetch)

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    await loadPremiumThemes(fakeToken)

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/premium/themes',
      expect.objectContaining({
        credentials: 'include',
        headers: { Authorization: `Bearer ${fakeToken}` },
      }),
    )
  })

  it('omits Authorization header when token is empty string', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ themes: [] }),
    } as Response)
    vi.stubGlobal('fetch', mockFetch)

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    await loadPremiumThemes('')

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/premium/themes',
      expect.objectContaining({
        credentials: 'include',
        headers: {},
      }),
    )
  })

  it('token parameter is optional — works with no arguments', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ themes: [] }),
    } as Response))

    const { loadPremiumThemes } = await import('../usePremiumThemes')
    // Should not throw
    await expect(loadPremiumThemes()).resolves.toBeUndefined()
  })
})

describe('unloadPremiumThemes', () => {
  beforeEach(() => {
    document.getElementById('premium-themes')?.remove()
    vi.resetModules()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('removes the premium-themes style element if present', async () => {
    const el = document.createElement('style')
    el.id = 'premium-themes'
    el.textContent = '.test {}'
    document.head.appendChild(el)

    expect(document.getElementById('premium-themes')).not.toBeNull()

    const { unloadPremiumThemes } = await import('../usePremiumThemes')
    unloadPremiumThemes()

    expect(document.getElementById('premium-themes')).toBeNull()
  })

  it('is a no-op when element does not exist', async () => {
    const { unloadPremiumThemes } = await import('../usePremiumThemes')
    // Should not throw
    expect(() => unloadPremiumThemes()).not.toThrow()
  })
})
