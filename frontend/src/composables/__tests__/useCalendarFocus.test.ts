import { describe, it, expect, beforeEach } from 'vitest'
import { resetFocusedDay, useCalendarFocus } from '../useCalendarFocus'

describe('useCalendarFocus', () => {
  beforeEach(() => {
    resetFocusedDay()
  })

  it('initializes focusedDay to today', () => {
    const today = new Date().toISOString().slice(0, 10)
    const { focusedDay } = useCalendarFocus()
    expect(focusedDay.value).toBe(today)
  })

  it('setFocusedDay updates focusedDay', () => {
    const { focusedDay, setFocusedDay } = useCalendarFocus()
    setFocusedDay('2024-06-15')
    expect(focusedDay.value).toBe('2024-06-15')
  })

  it('focusedDay is shared across multiple useCalendarFocus() calls', () => {
    const a = useCalendarFocus()
    const b = useCalendarFocus()
    a.setFocusedDay('2024-01-01')
    expect(b.focusedDay.value).toBe('2024-01-01')
  })

  it('resetFocusedDay returns focusedDay to today', () => {
    const { focusedDay, setFocusedDay } = useCalendarFocus()
    setFocusedDay('2020-01-01')
    resetFocusedDay()
    expect(focusedDay.value).toBe(new Date().toISOString().slice(0, 10))
  })
})
