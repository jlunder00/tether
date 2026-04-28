import { describe, it, expect } from 'vitest'
import { computeOverlapLayout, type LayoutEvent } from '../useOverlapLayout'

function ev(id: string, startHour: number, endHour: number): LayoutEvent {
  const date = '2026-04-27'
  return {
    id,
    start_time: `${date}T${String(startHour).padStart(2,'0')}:00:00`,
    end_time:   `${date}T${String(endHour).padStart(2,'0')}:00:00`,
  }
}

describe('computeOverlapLayout', () => {
  it('single event fills full width', () => {
    const result = computeOverlapLayout([ev('a', 9, 10)])
    expect(result['a'].leftPercent).toBe(0)
    expect(result['a'].widthPercent).toBe(100)
  })

  it('two overlapping events split evenly', () => {
    const result = computeOverlapLayout([ev('a', 9, 10), ev('b', 9, 10)])
    expect(result['a'].leftPercent).toBe(0)
    expect(result['a'].widthPercent).toBe(50)
    expect(result['b'].leftPercent).toBe(50)
    expect(result['b'].widthPercent).toBe(50)
  })

  it('non-overlapping events each fill full width', () => {
    const result = computeOverlapLayout([ev('a', 9, 10), ev('b', 11, 12)])
    expect(result['a'].widthPercent).toBe(100)
    expect(result['b'].widthPercent).toBe(100)
  })

  it('three-way overlap splits into thirds', () => {
    const result = computeOverlapLayout([ev('a', 9, 12), ev('b', 10, 11), ev('c', 10, 11)])
    expect(result['a'].widthPercent).toBeCloseTo(33.33, 0)
    expect(result['b'].widthPercent).toBeCloseTo(33.33, 0)
    expect(result['c'].widthPercent).toBeCloseTo(33.33, 0)
  })

  it('sequential overlapping groups are independent', () => {
    const result = computeOverlapLayout([
      ev('a', 9, 10), ev('b', 9, 10),
      ev('c', 11, 12), ev('d', 11, 12),
    ])
    expect(result['a'].widthPercent).toBe(50)
    expect(result['c'].widthPercent).toBe(50)
  })
})
