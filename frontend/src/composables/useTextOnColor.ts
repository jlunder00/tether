/**
 * Pick a foreground color (light or dark) that contrasts a given hex bg.
 *
 * Used for chips whose background is a user/motif/event color and therefore
 * not theme-bound — `text-white` looks great on saturated dark bgs but fails
 * on lighter motif palettes (notably Paper). WCAG relative luminance with a
 * 0.5 threshold is the cheap, reliable heuristic.
 *
 * Returns `#0a0a0a` (near-black) for light bgs, `#ffffff` for dark bgs, and
 * `#ffffff` for unparseable inputs (e.g. `var(--motif-anchor)`) — the same
 * default the chips had before.
 */

interface RGB { r: number; g: number; b: number }

function parseHex(input: string): RGB | null {
  const m = input.trim().match(/^#([\da-f]{3}|[\da-f]{6})$/i)
  if (!m) return null
  const hex = m[1]
  if (hex.length === 3) {
    return {
      r: parseInt(hex[0] + hex[0], 16),
      g: parseInt(hex[1] + hex[1], 16),
      b: parseInt(hex[2] + hex[2], 16),
    }
  }
  return {
    r: parseInt(hex.slice(0, 2), 16),
    g: parseInt(hex.slice(2, 4), 16),
    b: parseInt(hex.slice(4, 6), 16),
  }
}

function relativeLuminance({ r, g, b }: RGB): number {
  const ch = (c: number) => {
    const cs = c / 255
    return cs <= 0.03928 ? cs / 12.92 : ((cs + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
}

export function textOnColor(bg: string | null | undefined): string {
  if (!bg) return '#ffffff'
  const rgb = parseHex(bg)
  if (!rgb) return '#ffffff'
  return relativeLuminance(rgb) > 0.5 ? '#0a0a0a' : '#ffffff'
}
