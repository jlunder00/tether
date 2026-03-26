<script setup lang="ts">
const props = defineProps<{ tasks: string[] }>()
const emit = defineEmits<{ (e: 'update', tasks: string[]): void }>()

function update(index: number, value: string) {
  const t = [...props.tasks]; t[index] = value; emit('update', t)
}
function add() { emit('update', [...props.tasks, '']) }
function remove(i: number) { emit('update', props.tasks.filter((_, j) => j !== i)) }
</script>

<template>
  <ul class="space-y-1">
    <li v-for="(task, i) in tasks" :key="i" class="flex gap-2 items-center">
      <input :value="task" @change="update(i, ($event.target as HTMLInputElement).value)"
        class="flex-1 bg-transparent border-b border-white/20 focus:border-white/60 outline-none text-sm py-0.5" />
      <button @click="remove(i)" class="text-white/30 hover:text-white/70 text-xs">✕</button>
    </li>
  </ul>
  <button @click="add" class="mt-2 text-xs text-white/40 hover:text-white/70">+ Add task</button>
</template>
