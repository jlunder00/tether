import { describe, it, expect } from 'vitest'
import { parseRrule, buildRrule } from '../useRruleParser'

describe('parseRrule', () => {
  it('parses null to none state', () => {
    expect(parseRrule(null).freq).toBe('none')
  })

  it('parses FREQ=DAILY;INTERVAL=3', () => {
    const s = parseRrule('FREQ=DAILY;INTERVAL=3')
    expect(s.freq).toBe('daily')
    expect(s.interval).toBe(3)
  })

  it('parses FREQ=WEEKLY;INTERVAL=2;BYDAY=MO', () => {
    const s = parseRrule('FREQ=WEEKLY;INTERVAL=2;BYDAY=MO')
    expect(s.freq).toBe('weekly')
    expect(s.interval).toBe(2)
    expect(s.byday).toEqual(['MO'])
  })

  it('parses FREQ=MONTHLY;BYDAY=3TU', () => {
    const s = parseRrule('FREQ=MONTHLY;BYDAY=3TU')
    expect(s.freq).toBe('monthly')
    expect(s.monthlyMode).toBe('byday')
    expect(s.nthWeekday).toBe(3)
    expect(s.byday).toEqual(['TU'])
  })

  it('parses FREQ=YEARLY', () => {
    expect(parseRrule('FREQ=YEARLY').freq).toBe('yearly')
  })

  it('parses COUNT=5 end condition', () => {
    const s = parseRrule('FREQ=DAILY;COUNT=5')
    expect(s.endMode).toBe('count')
    expect(s.count).toBe(5)
  })

  it('parses UNTIL end condition', () => {
    const s = parseRrule('FREQ=DAILY;UNTIL=20261231T000000Z')
    expect(s.endMode).toBe('until')
    expect(s.until).toBe('2026-12-31')
  })
})

describe('buildRrule', () => {
  it('returns null for none freq', () => {
    expect(buildRrule({ freq: 'none', interval: 1, byday: [], monthlyMode: 'date', nthWeekday: 1, endMode: 'never', count: 1, until: '' })).toBeNull()
  })

  it('builds FREQ=DAILY;INTERVAL=2', () => {
    expect(buildRrule({ freq: 'daily', interval: 2, byday: [], monthlyMode: 'date', nthWeekday: 1, endMode: 'never', count: 1, until: '' }))
      .toBe('FREQ=DAILY;INTERVAL=2')
  })

  it('builds FREQ=WEEKLY;BYDAY=TU,TH', () => {
    expect(buildRrule({ freq: 'weekly', interval: 1, byday: ['TU', 'TH'], monthlyMode: 'date', nthWeekday: 1, endMode: 'never', count: 1, until: '' }))
      .toBe('FREQ=WEEKLY;BYDAY=TU,TH')
  })

  it('builds FREQ=MONTHLY;BYDAY=2WE', () => {
    expect(buildRrule({ freq: 'monthly', interval: 1, byday: ['WE'], monthlyMode: 'byday', nthWeekday: 2, endMode: 'never', count: 1, until: '' }))
      .toBe('FREQ=MONTHLY;BYDAY=2WE')
  })

  it('appends COUNT', () => {
    const r = buildRrule({ freq: 'daily', interval: 1, byday: [], monthlyMode: 'date', nthWeekday: 1, endMode: 'count', count: 10, until: '' })
    expect(r).toContain('COUNT=10')
  })

  it('appends UNTIL', () => {
    const r = buildRrule({ freq: 'daily', interval: 1, byday: [], monthlyMode: 'date', nthWeekday: 1, endMode: 'until', count: 1, until: '2026-12-31' })
    expect(r).toContain('UNTIL=20261231')
  })
})
