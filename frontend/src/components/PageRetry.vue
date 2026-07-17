<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'

defineProps<{
  message?: string
  loading?: boolean
}>()

const emit = defineEmits<{ (e: 'retry'): void }>()
const { t } = useI18n()
</script>

<template>
  <div
    class="flex flex-col sm:flex-row sm:items-center gap-3 p-4 ui-card border-amber-200/80 dark:border-amber-800/40 bg-amber-50/50 dark:bg-amber-950/20"
    role="alert"
  >
    <div class="flex-1 min-w-0">
      <p class="text-sm text-amber-900 dark:text-amber-200 font-medium">
        {{ message || t('common.loadFailed') }}
      </p>
      <p class="text-xs text-amber-700/80 dark:text-amber-400/80 mt-0.5">
        {{ t('common.retryHint') }}
      </p>
    </div>
    <button
      type="button"
      class="ui-btn-secondary !px-3 !py-1.5 !text-xs shrink-0"
      :disabled="loading"
      @click="emit('retry')"
    >
      <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
      {{ t('common.retry') }}
    </button>
  </div>
</template>
