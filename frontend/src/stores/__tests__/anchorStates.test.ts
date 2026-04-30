import { describe, it, expect } from 'vitest'
import { computeAnchorStates } from '../anchors'
import type { Anchor } from '../anchors'

function makeAnchor(time: string, id: string): Anchor {
  return {
    id,
    name: `Anchor ${id}`,
    time,
    duration_minutes: 60,
    flexibility: 'flexible',
    strictness: 1,
    color: '#fff',
    position: 0,
    followup_config: null,
    motif: null,
  }
}

const anchors: Anchor[] = [
  makeAnchor('08:00', 'a1'),
  makeAnchor('12:00', 'a2'),
  makeAnchor('17:00', 'a3'),
]

describe('computeAnchorStates', () => {
  it('marks first anchor as now when time is before all anchor times', () => {
    const now = new Date()
    now.setHours(6, 0, 0, 0)
    const states = computeAnchorStates(anchors, now)
    expect(states.get('a1')).toBe('now')
    expect(states.get('a2')).toBe('future')
    expect(states.get('a3')).toBe('future')
  })

  it('marks last anchor as now when time is after all anchor times', () => {
    const now = new Date()
    now.setHours(20, 0, 0, 0)
    const states = computeAnchorStates(anchors, now)
    expect(states.get('a1')).toBe('past')
    expect(states.get('a2')).toBe('past')
    expect(states.get('a3')).toBe('now')
  })

  it('marks the correct anchor as now for mid-day time', () => {
    const now = new Date()
    now.setHours(14, 0, 0, 0)
    const states = computeAnchorStates(anchors, now)
    expect(states.get('a1')).toBe('past')
    expect(states.get('a2')).toBe('now')
    expect(states.get('a3')).toBe('future')
  })

  it('marks all anchors past current as future', () => {
    const now = new Date()
    now.setHours(9, 0, 0, 0)
    const states = computeAnchorStates(anchors, now)
    expect(states.get('a1')).toBe('now')
    expect(states.get('a2')).toBe('future')
    expect(states.get('a3')).toBe('future')
  })
})
