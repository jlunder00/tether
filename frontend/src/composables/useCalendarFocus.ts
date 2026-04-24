import { ref } from 'vue'

function todayString(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// Module-level so focus is shared across all callers (e.g. day header + grid column).
// resetFocusedDay() is exported for tests only.
const focusedDay = ref(todayString())

export function resetFocusedDay() {
  focusedDay.value = todayString()
}

export function useCalendarFocus() {
  function setFocusedDay(day: string) {
    focusedDay.value = day
  }

  return { focusedDay, setFocusedDay }
}
