/**
 * Verifies that themes.css defines the six semantic status-priority tokens
 * in every theme variant (13 total: dark + light per theme, paper light-only).
 *
 * These tokens are required before the Phase I notification sidebar can be
 * implemented. See notification-system-overhaul.md §9 and Phase H.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { resolve, dirname } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const themesCss = readFileSync(resolve(__dirname, '../themes.css'), 'utf-8')

// The six tokens every theme variant must define.
const REQUIRED_TOKENS = [
  '--status-urgent',
  '--status-urgent-bg',
  '--status-urgent-fg',
  '--status-important',
  '--status-important-bg',
  '--status-important-fg',
] as const

/**
 * Themes and a substring unique to each variant's selector block.
 * We find the first occurrence of the substring, then extract the
 * immediately following { ... } block.
 */
const THEME_VARIANTS: Record<string, string> = {
  'tether (dark/default)': '[data-theme="tether"][data-mode="dark"]',
  'tether (light)':        '[data-theme="tether"][data-mode="light"]',
  'horizon (dark)':        '[data-theme="horizon"][data-mode="dark"]',
  'horizon (light)':       '[data-theme="horizon"][data-mode="light"]',
  'contrast (dark)':       '[data-theme="contrast"][data-mode="dark"]',
  'contrast (light)':      '[data-theme="contrast"][data-mode="light"]',
  'terminal (dark)':       '[data-theme="terminal"][data-mode="dark"]',
  'terminal (light)':      '[data-theme="terminal"][data-mode="light"]',
  'solstice (dark)':       '[data-theme="solstice"][data-mode="dark"]',
  'solstice (light)':      '[data-theme="solstice"][data-mode="light"]',
  'dracula (dark)':        '[data-theme="dracula"][data-mode="dark"]',
  'dracula (light)':       '[data-theme="dracula"][data-mode="light"]',
  'paper':                 '[data-theme="paper"]',
}

/**
 * Finds the first occurrence of `selectorSubstring` in `css` and extracts
 * the content of the immediately following { ... } block (non-nested).
 */
function extractBlockAfterSelector(css: string, selectorSubstring: string): string | null {
  const idx = css.indexOf(selectorSubstring)
  if (idx === -1) return null
  const braceOpen = css.indexOf('{', idx)
  if (braceOpen === -1) return null
  const braceClose = css.indexOf('}', braceOpen)
  if (braceClose === -1) return null
  return css.slice(braceOpen, braceClose + 1)
}

describe('themes.css — semantic status-priority tokens', () => {
  for (const [label, selectorSubstring] of Object.entries(THEME_VARIANTS)) {
    describe(label, () => {
      it('defines all six --status-urgent/important tokens', () => {
        const block = extractBlockAfterSelector(themesCss, selectorSubstring)

        expect(
          block,
          `No block found for selector containing: ${selectorSubstring}`,
        ).not.toBeNull()

        for (const token of REQUIRED_TOKENS) {
          expect(
            block,
            `Token ${token} missing in "${label}" block`,
          ).toContain(token)
        }
      })
    })
  }
})
