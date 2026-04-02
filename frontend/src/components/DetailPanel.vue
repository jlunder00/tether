<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

function close() {
  router.back()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <!-- Backdrop -->
    <div class="fixed inset-0 z-40 bg-black/40" @click="close" />

    <!-- Panel -->
    <div class="fixed top-0 right-0 z-50 h-full w-full sm:w-[480px] lg:w-[520px] bg-gray-900 border-l border-white/10 shadow-2xl overflow-y-auto animate-slide-in">
      <slot />
    </div>
  </Teleport>
</template>

<style>
@keyframes slide-in {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.animate-slide-in {
  animation: slide-in 0.2s ease-out;
}
</style>
