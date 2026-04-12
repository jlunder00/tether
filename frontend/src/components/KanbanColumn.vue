<script setup lang="ts">
import { computed } from 'vue'
import TaskCard from './TaskCard.vue'
import GroupContainer from './GroupContainer.vue'
import type { Task } from '../stores/plan'
import { useMilestoneStore } from '../stores/milestones'
import type { KanbanColumn } from '../stores/kanban'

const props = defineProps<{
  column: KanbanColumn
  tasks: Task[]
}>()

const milestoneStore = useMilestoneStore()

/** Group tasks by context_subject, then by milestone within each context */
const grouped = computed(() => {
  const byContext: Record<string, Task[]> = {}
  for (const task of props.tasks) {
    const ctx = task.context_subject ?? '__uncategorized__'
    if (!byContext[ctx]) byContext[ctx] = []
    byContext[ctx].push(task)
  }
  // Sort: Uncategorized last
  const sorted = Object.entries(byContext).sort(([a], [b]) => {
    if (a === '__uncategorized__') return 1
    if (b === '__uncategorized__') return -1
    return a.localeCompare(b)
  })

  return sorted.map(([ctx, tasks]) => {
    const label = ctx === '__uncategorized__' ? 'Uncategorized' : ctx
    // Sub-group by milestone
    const byMilestone: Record<string, { name: string; color: string | null; tasks: Task[] }> = {}
    const ungrouped: Task[] = []

    for (const task of tasks) {
      const milestones = milestoneStore.taskMilestones[task.id]
      if (milestones?.length) {
        const m = milestones[0]
        if (!byMilestone[m.id]) byMilestone[m.id] = { name: m.name, color: m.color, tasks: [] }
        byMilestone[m.id].tasks.push(task)
      } else {
        ungrouped.push(task)
      }
    }

    return {
      label,
      tasks,
      milestoneGroups: Object.values(byMilestone),
      ungrouped,
    }
  })
})
</script>

<template>
  <div class="flex flex-col min-w-[320px] max-w-[380px] bg-white/[0.03] border border-white/10 rounded-xl flex-shrink-0">
    <!-- Column header -->
    <div class="flex items-center gap-2 px-3 py-2.5 border-b border-white/10">
      <span v-if="column.color" class="w-2.5 h-2.5 rounded-full flex-shrink-0" :style="{ background: column.color }" />
      <span class="text-sm font-semibold uppercase tracking-wide"
            :style="column.color ? { color: column.color } : {}">
        {{ column.name }}
      </span>
      <span class="text-xs text-white/30 ml-auto">{{ tasks.length }}</span>
    </div>

    <!-- Scrollable body -->
    <div class="flex-1 overflow-y-auto p-2 space-y-2" style="max-height: calc(100vh - 140px);">
      <template v-if="!tasks.length">
        <p class="text-white/20 text-xs text-center py-4">No tasks</p>
      </template>

      <template v-for="group in grouped" :key="group.label">
        <GroupContainer :label="group.label" :collapsible="true" :level="0">
          <template #header-right>
            <span class="text-xs text-white/30">{{ group.tasks.length }}</span>
          </template>

          <!-- Milestone sub-groups -->
          <GroupContainer
            v-for="mg in group.milestoneGroups"
            :key="mg.name"
            :label="mg.name"
            :color="mg.color ?? undefined"
            :level="1"
            class="mb-1">
            <ul class="space-y-0.5">
              <TaskCard
                v-for="task in mg.tasks"
                :key="task.id"
                :task="task"
                :editable="false"
                :showRemove="false"
                :showDetailLink="false"
                :compact="true" :hideTags="true" />
            </ul>
          </GroupContainer>

          <!-- Ungrouped tasks -->
          <ul v-if="group.ungrouped.length" class="space-y-0.5">
            <TaskCard
              v-for="task in group.ungrouped"
              :key="task.id"
              :task="task"
              :editable="false"
              :showRemove="false"
              :showDetailLink="false"
              :compact="true" :hideTags="true" />
          </ul>
        </GroupContainer>
      </template>
    </div>
  </div>
</template>
