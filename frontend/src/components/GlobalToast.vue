<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { useToast } from '../composables/useToast'

const { toasts, dismiss } = useToast()
</script>

<template>
  <Teleport to="body">
    <div class="fixed bottom-6 right-6 z-[200] flex flex-col gap-2 pointer-events-none max-w-sm w-[min(100vw-2rem,24rem)]">
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
          role="status"
          class="pointer-events-auto flex items-start gap-2 px-4 py-2.5 text-sm shadow-lg border rounded-md"
          :class="{
            'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800/60 text-gray-900 dark:text-gray-100': toast.type === 'info',
            'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-200 dark:border-emerald-800/50 text-emerald-700 dark:text-emerald-400': toast.type === 'success',
            'bg-rose-50 dark:bg-rose-500/10 border-rose-200 dark:border-rose-800/50 text-rose-700 dark:text-rose-400': toast.type === 'error',
          }"
        >
          <span class="flex-1 break-words leading-relaxed">{{ toast.message }}</span>
          <button
            type="button"
            class="shrink-0 mt-0.5 p-0.5 rounded opacity-60 hover:opacity-100 transition-opacity"
            :aria-label="'Dismiss'"
            @click="dismiss(toast.id)"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
