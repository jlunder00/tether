import { describe, it, expect, beforeEach } from 'vitest'
import { resetFocusedDay, useCalendarFocus } from '../useCalendarFocus'

describe('useCalendarFocus', () => {
  beforeEach(() => {
    resetFocusedDay()
  })

  it('initializes focusedDay to today', () => {
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    expect(focusedDay.value).toBe(today)
  })
})
