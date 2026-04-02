import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../lib/api'

export type MilestoneStatus = 'pending' | 'in_progress' | 'done' | 'blocked'

export interface MilestoneTask {
  id: string
  text: string | null
  status: string
  plan_date: string | null
  anchor_id: string | null
}

export interface Milestone {
  id: string
  context_subject: string
  name: string
  description: string | null
  target_date: string | null
  status: MilestoneStatus
  status_override: boolean
  created_at: string
  updated_at: string
  task_count: number
  done_count: number
  task_ids: string[]
  tasks: MilestoneTask[]
}

export const useMilestoneStore = defineStore('milestones', () => {
  const all = ref<Milestone[]>([])

  const taskMilestones = computed<Record<string, Milestone[]>>(() => {
    const map: Record<string, Milestone[]> = {}
    for (const m of all.value) {
      for (const tid of m.task_ids) {
        if (!map[tid]) map[tid] = []
        map[tid].push(m)
      }
    }
    return map
  })

  const bySubject = computed<Record<string, Milestone[]>>(() => {
    const map: Record<string, Milestone[]> = {}
    for (const m of all.value) {
      if (!map[m.context_subject]) map[m.context_subject] = []
      map[m.context_subject].push(m)
    }
    return map
  })

  async function fetchAll() {
    const resp = await api('/api/milestones')
    all.value = await resp.json()
  }

  async function createMilestone(subject: string, name: string, description?: string, targetDate?: string) {
    const resp = await api(`/api/context/${encodeURIComponent(subject)}/milestones`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: description ?? null, target_date: targetDate ?? null }),
    })
    const m: Milestone = await resp.json()
    all.value = [...all.value, m]
    return m
  }

  async function patchMilestone(id: string, fields: Partial<Pick<Milestone, 'name' | 'description' | 'target_date' | 'status'>>) {
    const resp = await api(`/api/milestones/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    const updated: Milestone = await resp.json()
    all.value = all.value.map(m => m.id === id ? updated : m)
    return updated
  }

  async function deleteMilestone(id: string) {
    await api(`/api/milestones/${id}`, { method: 'DELETE' })
    all.value = all.value.filter(m => m.id !== id)
  }

  async function linkTask(milestoneId: string, taskId: string) {
    await api(`/api/milestones/${milestoneId}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId }),
    })
    await fetchAll()
  }

  async function unlinkTask(milestoneId: string, taskId: string) {
    await api(`/api/milestones/${milestoneId}/tasks/${taskId}`, { method: 'DELETE' })
    await fetchAll()
  }

  return { all, taskMilestones, bySubject, fetchAll, createMilestone, patchMilestone, deleteMilestone, linkTask, unlinkTask }
})
