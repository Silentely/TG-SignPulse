<script setup lang="ts">
import { X, CheckCircle2, AlertCircle, Info } from 'lucide-vue-next'
import { useToast } from '../composables/useToast'
import { useI18n } from '../composables/useI18n'

const { toasts, dismiss } = useToast()
const { t } = useI18n()
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
          class="pointer-events-auto flex items-start gap-2.5 px-3.5 py-2.5 text-sm shadow-[var(--sp-shadow-md)] border backdrop-blur-sm"
          :class="{
            'bg-white/95 dark:bg-[var(--sp-bg-elevated)]/95 border-gray-200 dark:border-[var(--sp-border)] text-gray-900 dark:text-gray-100': toast.type === 'info',
            'bg-emerald-50/95 dark:bg-emerald-950/80 border-emerald-200 dark:border-emerald-800/50 text-emerald-800 dark:text-emerald-300': toast.type === 'success',
            'bg-rose-50/95 dark:bg-rose-950/80 border-rose-200 dark:border-rose-800/50 text-rose-800 dark:text-rose-300': toast.type === 'error',
          }"
        >
          <CheckCircle2
            v-if="toast.type === 'success'"
            class="w-4 h-4 shrink-0 mt-0.5 opacity-90"
          />
          <AlertCircle
            v-else-if="toast.type === 'error'"
            class="w-4 h-4 shrink-0 mt-0.5 opacity-90"
          />
          <Info
            v-else
            class="w-4 h-4 shrink-0 mt-0.5 opacity-70"
          />
          <div class="flex-1 min-w-0">
            <div class="break-words leading-relaxed font-medium">{{ toast.message }}</div>
            <div
              v-if="toast.description"
              class="mt-1 text-xs opacity-80 whitespace-pre-wrap break-words leading-relaxed font-normal"
            >
              {{ toast.description }}
            </div>
          </div>
          <button
            type="button"
            class="shrink-0 mt-0.5 p-0.5 rounded opacity-50 hover:opacity-100 transition-opacity"
            :aria-label="t('common.close')"
            @click="dismiss(toast.id)"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>
