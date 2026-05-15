<script setup lang="ts">
import { useToast } from '../composables/useToast'

const { toasts } = useToast()
</script>

<template>
  <Teleport to="body">
    <div class="fixed bottom-6 right-6 z-[200] flex flex-col gap-2 pointer-events-none max-w-sm">
      <TransitionGroup
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="opacity-0 translate-y-2 scale-95"
        enter-to-class="opacity-100 translate-y-0 scale-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="opacity-100 translate-y-0 scale-100"
        leave-to-class="opacity-0 translate-y-2 scale-95"
      >
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="pointer-events-auto px-4 py-2.5 text-sm shadow-lg border"
          :class="{
            'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800/60 text-gray-900 dark:text-gray-100': toast.type === 'info',
            'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-800/50 text-emerald-700 dark:text-emerald-400': toast.type === 'success',
            'bg-rose-50 dark:bg-rose-500/10 border-rose-200 dark:border-rose-800/50 text-rose-700 dark:text-rose-400': toast.type === 'error',
          }"
        >
          {{ toast.message }}
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
