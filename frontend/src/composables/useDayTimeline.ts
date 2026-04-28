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

export function eventHeightPx(startTime: string, endTime: string): number {
  const durationMin = (new Date(endTime).getTime() - new Date(startTime).getTime()) / 60_000
  return Math.max(20, durationMin * PX_PER_MINUTE)
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
