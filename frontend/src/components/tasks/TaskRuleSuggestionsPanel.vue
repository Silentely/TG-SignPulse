<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Check, X, AlertTriangle, Sparkles, RefreshCw, ExternalLink } from 'lucide-vue-next'
import {
  listRuleSuggestions,
  applyRuleSuggestion,
  dismissRuleSuggestion,
  type RuleSuggestion,
} from '../../lib/api/semantic'
import { useI18n } from '../../composables/useI18n'

const props = withDefaults(
  defineProps<{
    accountName: string
    taskName: string
    hideWhenEmpty?: boolean
    showNavigateToTasks?: boolean
  }>(),
  {
    hideWhenEmpty: false,
    showNavigateToTasks: false,
  }
)

const emit = defineEmits<{
  (e: 'applied', suggestion: RuleSuggestion): void
}>()

const { t } = useI18n()

let router: any = null
try {
  router = useRouter()
} catch {
  // router not injected in some test environments
}

const handleNavigateToTasks = () => {
  if (router?.push) {
    void router.push({
      name: 'tasks',
      query: {
        account: props.accountName || undefined,
        task: props.taskName,
        tab: 'logs',
      },
    })
  }
}

const suggestions = ref<RuleSuggestion[]>([])
const loading = ref(false)
const actionLoading = ref<Record<string, boolean>>({})
const errorMsg = ref('')

const fetchSuggestions = async () => {
  if (!props.taskName) return
  loading.value = true
  errorMsg.value = ''
  try {
    const items = await listRuleSuggestions({
      account_name: props.accountName,
      task_name: props.taskName,
      status: 'pending',
    })
    suggestions.value = items || []
  } catch (err: any) {
    errorMsg.value = err?.message || t('ruleSuggestions.loadFailed')
  } finally {
    loading.value = false
  }
}

const handleApply = async (s: RuleSuggestion) => {
  actionLoading.value[s.id] = true
  errorMsg.value = ''
  try {
    await applyRuleSuggestion(s.id, {
      account_name: props.accountName,
      task_name: props.taskName,
    })
    suggestions.value = suggestions.value.filter((item) => item.id !== s.id)
    emit('applied', s)
  } catch (err: any) {
    if (err?.status === 409 || String(err?.message || '').includes('SEMANTIC_CONFIG_CHANGED')) {
      errorMsg.value = t('ruleSuggestions.errorConflict')
    } else {
      errorMsg.value = err?.message || t('ruleSuggestions.applyFailed')
    }
  } finally {
    actionLoading.value[s.id] = false
  }
}

const handleDismiss = async (s: RuleSuggestion) => {
  actionLoading.value[s.id] = true
  errorMsg.value = ''
  try {
    await dismissRuleSuggestion(s.id, {
      account_name: props.accountName,
      task_name: props.taskName,
    })
    suggestions.value = suggestions.value.filter((item) => item.id !== s.id)
  } catch (err: any) {
    errorMsg.value = err?.message || t('ruleSuggestions.dismissFailed')
  } finally {
    actionLoading.value[s.id] = false
  }
}

watch(() => [props.accountName, props.taskName], () => {
  fetchSuggestions()
})

onMounted(() => {
  fetchSuggestions()
})
</script>

<template>
  <div
    v-if="!hideWhenEmpty || suggestions.length > 0"
    class="ui-card p-3 mb-3 text-sm border-amber-500/20 dark:border-amber-500/30 bg-[var(--sp-surface)] dark:bg-[var(--sp-surface-elevated)] space-y-2.5"
  >
    <div class="flex items-center justify-between pb-2 border-b border-[var(--sp-border)]">
      <div class="flex items-center gap-2 font-medium text-[var(--sp-text)]">
        <Sparkles class="w-4 h-4 text-amber-500 dark:text-amber-400" />
        <span>{{ t('ruleSuggestions.title') }}</span>
        <span
          v-if="suggestions.length > 0"
          class="px-1.5 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 font-mono font-medium"
        >
          {{ suggestions.length }}
        </span>
      </div>
      <div class="flex items-center gap-1.5">
        <button
          v-if="showNavigateToTasks"
          type="button"
          class="text-xs text-sky-600 dark:text-sky-400 hover:text-sky-500 dark:hover:text-sky-300 hover:underline inline-flex items-center gap-1 cursor-pointer mr-1"
          :title="t('ruleSuggestions.goToTasks')"
          @click="handleNavigateToTasks"
        >
          <ExternalLink class="w-3.5 h-3.5" />
          <span>{{ t('ruleSuggestions.goToTasks') }}</span>
        </button>
        <button
          type="button"
          class="ui-icon-btn !w-6 !h-6 text-[var(--sp-text-muted)] hover:text-[var(--sp-text)]"
          :disabled="loading"
          :title="t('ruleSuggestions.refresh')"
          @click="fetchSuggestions"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
        </button>
      </div>
    </div>

    <!-- 错误或冲突提示 -->
    <div
      v-if="errorMsg"
      class="flex items-start gap-2 p-2.5 rounded bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-rose-700 dark:text-rose-300 text-xs"
    >
      <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5 text-rose-500" />
      <span class="flex-1">{{ errorMsg }}</span>
    </div>

    <!-- 空状态 -->
    <div
      v-if="!loading && suggestions.length === 0"
      class="py-2.5 text-center text-xs text-[var(--sp-text-muted)] flex items-center justify-center gap-1.5"
    >
      <Check class="w-3.5 h-3.5 text-emerald-500 opacity-70" />
      <span>{{ t('ruleSuggestions.empty') }}</span>
    </div>

    <!-- 建议列表 -->
    <div v-else-if="suggestions.length > 0" class="space-y-2">
      <div
        v-for="s in suggestions"
        :key="s.id"
        class="p-2.5 rounded bg-[var(--sp-surface-subtle)] dark:bg-[var(--sp-surface)] border border-[var(--sp-border)] flex flex-col gap-2"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5">
            <span class="text-xs px-1.5 py-0.5 rounded bg-[var(--sp-surface-muted)] text-[var(--sp-text)] font-mono border border-[var(--sp-border)]">
              {{ s.kind }}
            </span>
            <span class="text-xs text-[var(--sp-text-secondary)] font-mono truncate max-w-[200px]" :title="s.patch.path">
              {{ s.patch.path }}
            </span>
          </div>
          <span
            v-if="s.confidence"
            class="text-[11px] text-[var(--sp-text-muted)] font-medium"
          >
            {{ t('ruleSuggestions.confidence') }} {{ (s.confidence * 100).toFixed(0) }}%
          </span>
        </div>

        <!-- 差异对比 -->
        <div class="grid grid-cols-2 gap-2 text-xs font-mono bg-[var(--sp-surface)] dark:bg-[var(--sp-surface-elevated)] p-2 rounded border border-[var(--sp-border)]">
          <div class="overflow-hidden">
            <div class="text-[10px] text-[var(--sp-text-muted)] mb-0.5 uppercase tracking-wider">{{ t('ruleSuggestions.currentConfig') }}</div>
            <div class="text-rose-600 dark:text-rose-400 truncate" :title="String(s.patch.old)">
              {{ s.patch.old !== undefined ? JSON.stringify(s.patch.old) : '-' }}
            </div>
          </div>
          <div class="overflow-hidden">
            <div class="text-[10px] text-[var(--sp-text-muted)] mb-0.5 uppercase tracking-wider">{{ t('ruleSuggestions.suggestedValue') }}</div>
            <div class="text-emerald-600 dark:text-emerald-400 truncate" :title="String(s.patch.value)">
              {{ JSON.stringify(s.patch.value) }}
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center justify-end gap-2 pt-0.5">
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1"
            :disabled="actionLoading[s.id]"
            @click="handleDismiss(s)"
          >
            <X class="w-3 h-3" />
            <span>{{ t('ruleSuggestions.dismiss') }}</span>
          </button>
          <button
            type="button"
            class="ui-btn-primary !py-1 !px-2.5 !text-xs !bg-emerald-600 hover:!bg-emerald-500 text-white inline-flex items-center gap-1 font-medium shadow-none"
            :disabled="actionLoading[s.id]"
            @click="handleApply(s)"
          >
            <Check class="w-3 h-3" />
            <span>{{ t('ruleSuggestions.apply') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
