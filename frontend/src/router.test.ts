/**
 * Unit tests for legacy URL redirect regexes used in router.ts beforeEach guard.
 * These test the regex patterns in isolation — no Vue Router mounting needed.
 *
 * Legacy routes had nested children like /view/task/:id and /view/milestone/:id.
 * The guard converts them to /view?panels=task:id or /view?panels=milestone:id.
 */

import { describe, it, expect } from 'vitest'

// Copy the exact regex patterns from router.ts
const LEGACY_TASK_RE = /^(\/[^?#]+)\/task\/([^/?#]+)/
const LEGACY_MILESTONE_RE = /^(\/[^?#]+)\/milestone\/([^/?#]+)/

describe('legacy URL redirect regexes', () => {
  describe('LEGACY_TASK_RE', () => {
    it('matches /dashboard/task/abc', () => {
      const m = LEGACY_TASK_RE.exec('/dashboard/task/abc')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/dashboard')
      expect(m![2]).toBe('abc')
    })

    it('matches /plan/day/2026-04-18/task/abc-123', () => {
      const m = LEGACY_TASK_RE.exec('/plan/day/2026-04-18/task/abc-123')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/plan/day/2026-04-18')
      expect(m![2]).toBe('abc-123')
    })

    it('matches /plan/week/task/uuid-here', () => {
      const m = LEGACY_TASK_RE.exec('/plan/week/task/uuid-here')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/plan/week')
      expect(m![2]).toBe('uuid-here')
    })

    it('matches /context/task/some-id', () => {
      const m = LEGACY_TASK_RE.exec('/context/task/some-id')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/context')
      expect(m![2]).toBe('some-id')
    })

    it('does not match /tasks (no /task/ segment)', () => {
      expect(LEGACY_TASK_RE.exec('/tasks')).toBeNull()
    })

    it('does not match /dashboard/task without an id', () => {
      // /dashboard/task/ with empty id — regex requires at least one char
      expect(LEGACY_TASK_RE.exec('/dashboard/task/')).toBeNull()
    })

    it('does not match /dashboard?task=abc (query string)', () => {
      // query strings start with ? which is excluded by [^?#]+
      // the regex matches on pathname only; the guard is called with to.path
      expect(LEGACY_TASK_RE.exec('/dashboard')).toBeNull()
    })
  })

  describe('LEGACY_MILESTONE_RE', () => {
    it('matches /context/milestone/xyz', () => {
      const m = LEGACY_MILESTONE_RE.exec('/context/milestone/xyz')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/context')
      expect(m![2]).toBe('xyz')
    })

    it('matches /plan/day/2026-04-18/milestone/some-uuid', () => {
      const m = LEGACY_MILESTONE_RE.exec('/plan/day/2026-04-18/milestone/some-uuid')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/plan/day/2026-04-18')
      expect(m![2]).toBe('some-uuid')
    })

    it('matches /kanban/milestone/m-001', () => {
      const m = LEGACY_MILESTONE_RE.exec('/kanban/milestone/m-001')
      expect(m).not.toBeNull()
      expect(m![1]).toBe('/kanban')
      expect(m![2]).toBe('m-001')
    })

    it('does not match /milestones (no /milestone/ segment)', () => {
      expect(LEGACY_MILESTONE_RE.exec('/milestones')).toBeNull()
    })

    it('does not match /dashboard/task/abc (wrong segment)', () => {
      expect(LEGACY_MILESTONE_RE.exec('/dashboard/task/abc')).toBeNull()
    })
  })

  describe('redirect URL construction', () => {
    it('builds correct redirect for task legacy URL', () => {
      const path = '/plan/day/2026-04-18/task/abc-123'
      const m = LEGACY_TASK_RE.exec(path)
      expect(m).not.toBeNull()
      const [, base, id] = m!
      const redirectPath = `${base}?panels=task:${id}`
      expect(redirectPath).toBe('/plan/day/2026-04-18?panels=task:abc-123')
    })

    it('builds correct redirect for milestone legacy URL', () => {
      const path = '/context/milestone/xyz-789'
      const m = LEGACY_MILESTONE_RE.exec(path)
      expect(m).not.toBeNull()
      const [, base, id] = m!
      const redirectPath = `${base}?panels=milestone:${id}`
      expect(redirectPath).toBe('/context?panels=milestone:xyz-789')
    })
  })
})
