// frontend/src/composables/useTheme.ts
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'

export type ThemeTier = 'free' | 'paid-oss' | 'paid' | 'premium'
export type MotifSlot = 'anchor' | 'focus' | 'calm' | 'energy' | 'care' | 'flow' | 'dusk' | 'quiet' | 'light' | 'dark'
export type TypeVoice = 'sharp' | 'editorial' | 'terminal'

export interface ThemeDef {
  id: string
  name: string
  tier: ThemeTier
  canvas: string
  accent: string
}

export const THEMES: ThemeDef[] = [
  { id: 'tether',   name: 'The Tether',    tier: 'free',     canvas: '#0E1117', accent: '#7C8AFF' },
  { id: 'horizon',  name: 'Horizon',       tier: 'free',     canvas: '#161512', accent: '#D4A85F' },
  { id: 'contrast', name: 'High Contrast', tier: 'free',     canvas: '#000000', accent: '#FFD43B' },
  { id: 'terminal', name: 'Terminal',      tier: 'paid-oss', canvas: '#0A0E0A', accent: '#50FA7B' },
  { id: 'solstice', name: 'Solstice',      tier: 'paid-oss', canvas: '#0B1418', accent: '#5FC8E6' },
  { id: 'dracula',  name: 'Dracula·Tether',tier: 'paid-oss', canvas: '#282A36', accent: '#BD93F9' },
  { id: 'paper',    name: 'Paper',         tier: 'paid-oss', canvas: '#FAFAF7', accent: '#1C1C1A' },
]

const VOICE: Record<string, TypeVoice> = {
  tether: 'sharp', horizon: 'editorial', contrast: 'sharp',
  terminal: 'terminal', solstice: 'sharp', dracula: 'terminal', paper: 'editorial',
}

// Check if running as community edition (self-hosted, all OSS themes unlocked)
// TODO: wire TETHER_EDITION into vite.config.ts define block
declare const __TETHER_EDITION__: string | undefined
const isCommunityEdition = (() => {
  try { return typeof __TETHER_EDITION__ !== 'undefined' && __TETHER_EDITION__ === 'community' }
  catch { return false }
})()

export function useTheme() {
  const auth = useAuthStore()
  // is_paid is optional on User — defaults to false until backend ships the field
  const isPaid = computed(() => !!auth.user?.is_paid)

  const activeTheme = ref(localStorage.getItem('tether-theme') ?? 'tether')
  const activeMode = ref<'light' | 'dark'>(
    (localStorage.getItem('tether-mode') as 'light' | 'dark') ??
    (new Date().getHours() >= 7 && new Date().getHours() < 19 ? 'light' : 'dark')
  )

  function isThemeUnlocked(theme: ThemeDef): boolean {
    if (theme.tier === 'free') return true
    if (theme.tier === 'paid-oss' && isCommunityEdition) return true
    if (theme.tier === 'paid-oss' || theme.tier === 'paid') return isPaid.value
    return false // premium tier always gated
  }

  function applyTheme(themeId: string) {
    const theme = THEMES.find(t => t.id === themeId)
    if (!theme || !isThemeUnlocked(theme)) return
    activeTheme.value = themeId
    localStorage.setItem('tether-theme', themeId)
    document.documentElement.dataset.theme = themeId
    document.documentElement.dataset.typeVoice = VOICE[themeId] ?? 'sharp'
    // Instant swap: briefly suppress the slow crossfade so user-triggered swaps feel crisp
    document.documentElement.dataset.themeSwap = 'instant'
    requestAnimationFrame(() => { delete document.documentElement.dataset.themeSwap })
  }

  /** Applies a theme to the DOM for live preview without persisting to localStorage.
   *  Bypasses the tier lock so any user can see how a theme looks before upgrading. */
  function previewTheme(themeId: string) {
    document.documentElement.dataset.theme = themeId
    document.documentElement.dataset.typeVoice = VOICE[themeId] ?? 'sharp'
  }

  function setMode(mode: 'light' | 'dark') {
    activeMode.value = mode
    localStorage.setItem('tether-mode', mode)
    document.documentElement.dataset.mode = mode
  }

  function autoMode() {
    const h = new Date().getHours()
    return h >= 7 && h < 19 ? 'light' : 'dark'
  }

  return { THEMES, activeTheme, activeMode, isPaid, isThemeUnlocked, applyTheme, previewTheme, setMode, autoMode, isCommunityEdition }
}
