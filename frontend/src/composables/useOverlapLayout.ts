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

  const result: Record<string, EventLayout> = {}
  for (const ev of sorted) {
    const evStart = new Date(ev.start_time).getTime()
    const evEnd = new Date(ev.end_time).getTime()
    const overlapping = sorted.filter(other => {
      const s = new Date(other.start_time).getTime()
      const e = new Date(other.end_time).getTime()
      return s < evEnd && e > evStart
    })
    const groupSize = overlapping.length
    const lane = eventLane.get(ev.id) ?? 0
    const widthPercent = 100 / groupSize
    const leftPercent = lane * widthPercent
    result[ev.id] = { leftPercent, widthPercent }
  }

  return result
}
