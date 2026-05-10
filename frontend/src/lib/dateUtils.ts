/**
 * Format a Date as YYYY-MM-DD in local time.
 * Equivalent to the many inline localDateString / localDateStr / localToday helpers.
 */
export function localDateString(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/**
 * Return today's date as YYYY-MM-DD in local time.
 */
export function localToday(): string {
  return localDateString(new Date())
}

/**
 * Offset a YYYY-MM-DD string by N calendar days (positive = future, negative = past).
 */
export function offsetDate(base: string, days: number): string {
  const d = new Date(base + 'T12:00:00')
  d.setDate(d.getDate() + days)
  return localDateString(d)
}
