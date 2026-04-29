import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../stores/auth', () => ({
  useAuthStore: () => ({ user: null }),
}))

import ThemeDrawer from '../ThemeDrawer.vue'

describe('ThemeDrawer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    delete document.documentElement.dataset.theme
    delete document.documentElement.dataset.mode
    delete document.documentElement.dataset.typeVoice
    localStorage.clear()
    // Remove any teleported nodes from a prior test
    while (document.body.firstChild) document.body.removeChild(document.body.firstChild)
  })

  it('does not render content when modelValue is false', () => {
    mount(ThemeDrawer, { props: { modelValue: false }, attachTo: document.body })
    expect(document.body.querySelector('[data-testid="theme-drawer"]')).toBeNull()
  })

  it('renders all 7 themes when open', () => {
    mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const swatches = document.body.querySelectorAll('[data-testid="theme-swatch"]')
    expect(swatches).toHaveLength(7)
    const ids = Array.from(swatches).map(s => s.getAttribute('data-theme-id'))
    expect(ids).toEqual(['tether','horizon','contrast','terminal','solstice','dracula','paper'])
  })

  it('hover on a swatch previews the theme on documentElement', () => {
    mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const horizon = document.body.querySelector('[data-theme-id="horizon"]') as HTMLElement
    expect(horizon).toBeTruthy()
    horizon.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
    expect(document.documentElement.dataset.theme).toBe('horizon')
  })

  it('clicking an unlocked theme applies it (persists + sets data-theme)', () => {
    mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const horizon = document.body.querySelector('[data-theme-id="horizon"]') as HTMLElement
    horizon.click()
    expect(document.documentElement.dataset.theme).toBe('horizon')
    expect(localStorage.getItem('tether-theme')).toBe('horizon')
  })

  it('clicking a paid (locked) theme previews but does not persist', () => {
    mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const dracula = document.body.querySelector('[data-theme-id="dracula"]') as HTMLElement
    dracula.click()
    expect(document.documentElement.dataset.theme).toBe('dracula')
    expect(localStorage.getItem('tether-theme')).toBeNull()
  })

  it('clicking close emits update:modelValue=false', () => {
    const wrapper = mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const closeBtn = document.body.querySelector('[data-testid="theme-drawer-close"]') as HTMLElement
    closeBtn.click()
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
  })

  it('clicking the backdrop emits update:modelValue=false', () => {
    const wrapper = mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const backdrop = document.body.querySelector('[data-testid="theme-drawer-backdrop"]') as HTMLElement
    backdrop.click()
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
  })

  it('day/night toggle calls setMode and reflects active mode', () => {
    mount(ThemeDrawer, { props: { modelValue: true }, attachTo: document.body })
    const light = document.body.querySelector('[data-testid="mode-light"]') as HTMLElement
    light.click()
    expect(document.documentElement.dataset.mode).toBe('light')
    expect(localStorage.getItem('tether-mode')).toBe('light')
    const dark = document.body.querySelector('[data-testid="mode-dark"]') as HTMLElement
    dark.click()
    expect(document.documentElement.dataset.mode).toBe('dark')
    expect(localStorage.getItem('tether-mode')).toBe('dark')
  })
})
