import type { Anchor } from '../stores/anchors'

// Configurable axis
export const AXIS_START_HOUR = 6   // 6am
export const AXIS_END_HOUR   = 24  // midnight
export const PX_PER_MINUTE   = 1.5 // tune to taste

export interface TimeWindow { start: Date; end: Date }

export function anchorWindow(anchor: Anchor, date: Date): TimeWindow {
  const [h, m] = anchor.time.split(':').map(Number)
  const start = new Date(date)
  start.setHours(h, m, 0, 0)
  const end = new Date(start.getTime() + anchor.duration_minutes * 60_000)
  return { start, end }
}

export function minutesFromAxisStart(dt: Date): number {
  return (dt.getHours() - AXIS_START_HOUR) * 60 + dt.getMinutes()
}

export function eventTopPx(startTime: string): number {
  const dt = new Date(startTime)
  return Math.max(0, minutesFromAxisStart(dt)) * PX_PER_MINUTE
}

/**
 * Height of an event block in pixels, clipped to the visible axis window.
 * Uses raw start position + duration (not end getHours()) so that events
 * crossing midnight (e.g. 11pm–1am) compute correctly when AXIS_END_HOUR=24.
 */
export function eventHeightPx(startTime: string, endTime: string): number {
  const axisStartMin = 0
  const axisEndMin = (AXIS_END_HOUR - AXIS_START_HOUR) * 60

  const rawStartMin = minutesFromAxisStart(new Date(startTime))
  const durationMin = (new Date(endTime).getTime() - new Date(startTime).getTime()) / 60_000

  const clampedStartMin = Math.max(axisStartMin, rawStartMin)
  // Compute end as start+duration so it works even when endTime wraps past midnight
  const clampedEndMin = Math.min(axisEndMin, rawStartMin + durationMin)
  const visibleMin = Math.max(0, clampedEndMin - clampedStartMin)
  return Math.max(20, visibleMin * PX_PER_MINUTE)
}

export function anchorBandTopPx(anchor: Anchor, date: Date): number {
  const { start } = anchorWindow(anchor, date)
  return Math.max(0, minutesFromAxisStart(start)) * PX_PER_MINUTE
}

export function anchorBandHeightPx(anchor: Anchor, date: Date): number {
  const { start, end } = anchorWindow(anchor, date)
  const durationMin = (end.getTime() - start.getTime()) / 60_000
  return durationMin * PX_PER_MINUTE
}

export const AXIS_TOTAL_PX = (AXIS_END_HOUR - AXIS_START_HOUR) * 60 * PX_PER_MINUTE

/**
 * Compute column layout for anchor bands when anchors overlap.
 * Returns a map from anchor id → { leftPercent, widthPercent }.
 * Non-overlapping anchors get leftPercent=0, widthPercent=100.
 * Overlapping anchors in a group of N are split into N equal columns.
 */
export function computeAnchorOverlapLayout(
  anchors: Anchor[],
  date: Date,
): Record<string, { leftPercent: number; widthPercent: number }> {
  const result: Record<string, { leftPercent: number; widthPercent: number }> = {}

  // Build time windows for each anchor
  const windows = anchors.map(a => ({ anchor: a, ...anchorWindow(a, date) }))

  // For each anchor, find all anchors it overlaps with (including itself)
  for (const w of windows) {
    const group = windows.filter(other =>
      w.start < other.end && w.end > other.start
    )
    const idx = group.findIndex(g => g.anchor.id === w.anchor.id)
    const n = group.length
    result[w.anchor.id] = {
      leftPercent: (idx / n) * 100,
      widthPercent: (1 / n) * 100,
    }
  }

  return result
}
