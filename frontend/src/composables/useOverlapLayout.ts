export interface LayoutEvent {
  id: string
  start_time: string
  end_time: string
}

export interface EventLayout {
  leftPercent: number
  widthPercent: number
}

/**
 * Compute side-by-side layout for events overlapping in time within a single day.
 * Greedily assigns each event to the first lane where it doesn't overlap the lane's
 * last event; group size is the count of all events overlapping with the target.
 */
export function computeOverlapLayout(events: LayoutEvent[]): Record<string, EventLayout> {
  if (events.length === 0) return {}

  const sorted = [...events].sort((a, b) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )

  const lanes: LayoutEvent[][] = []
  const eventLane = new Map<string, number>()

  for (const ev of sorted) {
    const evStart = new Date(ev.start_time).getTime()
    let placed = false
    for (let i = 0; i < lanes.length; i++) {
      const lastInLane = lanes[i][lanes[i].length - 1]
      const lastEnd = new Date(lastInLane.end_time).getTime()
      if (evStart >= lastEnd) {
        lanes[i].push(ev)
        eventLane.set(ev.id, i)
        placed = true
        break
      }
    }
    if (!placed) {
      eventLane.set(ev.id, lanes.length)
      lanes.push([ev])
    }
  }

  // Group events by connected overlap component (transitive overlap).
  // Column count = max lane index + 1 within that component, so chained
  // overlaps (A∩B, B∩C, A!∩C) get a consistent 3-column layout instead of
  // each event sizing itself by its own neighbor count.
  const adj = new Map<string, string[]>()
  for (const ev of sorted) adj.set(ev.id, [])
  for (let i = 0; i < sorted.length; i++) {
    const a = sorted[i]
    const aStart = new Date(a.start_time).getTime()
    const aEnd = new Date(a.end_time).getTime()
    for (let j = i + 1; j < sorted.length; j++) {
      const b = sorted[j]
      const bStart = new Date(b.start_time).getTime()
      const bEnd = new Date(b.end_time).getTime()
      if (bStart < aEnd && bEnd > aStart) {
        adj.get(a.id)!.push(b.id)
        adj.get(b.id)!.push(a.id)
      }
    }
  }

  const componentColumns = new Map<string, number>()
  const visited = new Set<string>()
  for (const ev of sorted) {
    if (visited.has(ev.id)) continue
    const stack = [ev.id]
    const component: string[] = []
    while (stack.length) {
      const id = stack.pop()!
      if (visited.has(id)) continue
      visited.add(id)
      component.push(id)
      for (const nb of adj.get(id) ?? []) if (!visited.has(nb)) stack.push(nb)
    }
    let maxLane = 0
    for (const id of component) maxLane = Math.max(maxLane, eventLane.get(id) ?? 0)
    const columns = maxLane + 1
    for (const id of component) componentColumns.set(id, columns)
  }

  const result: Record<string, EventLayout> = {}
  for (const ev of sorted) {
    const lane = eventLane.get(ev.id) ?? 0
    const columns = componentColumns.get(ev.id) ?? 1
    const widthPercent = 100 / columns
    const leftPercent = lane * widthPercent
    result[ev.id] = { leftPercent, widthPercent }
  }

  return result
}

export interface OverlapBand {
  topPx: number
  heightPx: number
}

/**
 * Given events and their overlap layout, return merged px bands covering all
 * time windows where multiple events overlap. Only events with widthPercent < 100
 * (i.e. in an overlap group) contribute to these bands.
 *
 * @param events     - The full event list for a column
 * @param layout     - Output of computeOverlapLayout for the same events
 * @param topFn      - Maps startTime ISO string → top-px in the column
 * @param heightFn   - Maps (startTime, endTime) ISO strings → height-px
 */
export function computeOverlapBands(
  events: LayoutEvent[],
  layout: Record<string, EventLayout>,
  topFn: (startTime: string) => number,
  heightFn: (startTime: string, endTime: string) => number,
): OverlapBand[] {
  const overlapping = events.filter(ev => (layout[ev.id]?.widthPercent ?? 100) < 100)
  if (!overlapping.length) return []

  const intervals = overlapping
    .map(ev => {
      const top = topFn(ev.start_time)
      return { top, bottom: top + heightFn(ev.start_time, ev.end_time) }
    })
    .sort((a, b) => a.top - b.top)

  const bands: OverlapBand[] = []
  let cur = intervals[0]
  for (let i = 1; i < intervals.length; i++) {
    if (intervals[i].top < cur.bottom) {
      cur = { top: cur.top, bottom: Math.max(cur.bottom, intervals[i].bottom) }
    } else {
      bands.push({ topPx: cur.top, heightPx: cur.bottom - cur.top })
      cur = intervals[i]
    }
  }
  bands.push({ topPx: cur.top, heightPx: cur.bottom - cur.top })
  return bands
}
