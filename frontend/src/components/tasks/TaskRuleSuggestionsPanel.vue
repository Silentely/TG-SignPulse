<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Check, X, AlertTriangle, Sparkles, RefreshCw } from 'lucide-vue-next'
import {
  listRuleSuggestions,
  applyRuleSuggestion,
  dismissRuleSuggestion,
  type RuleSuggestion,
} from '../../lib/api/semantic'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  accountName: string
  taskName: string
}>()

const emit = defineEmits<{
  (e: 'applied', suggestion: RuleSuggestion): void
}>()

const { t } = useI18n()

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
  <div class="space-y-3 p-3 bg-zinc-900/60 rounded-xl border border-zinc-800 text-sm">
    <div class="flex items-center justify-between pb-2 border-b border-zinc-800/80">
      <div class="flex items-center gap-2 font-medium text-zinc-200">
        <Sparkles class="w-4 h-4 text-amber-400" />
        <span>{{ t('ruleSuggestions.title') }}</span>
        <span
          v-if="suggestions.length > 0"
          class="px-1.5 py-0.5 text-xs rounded-full bg-amber-500/20 text-amber-300 font-mono"
        >
          {{ suggestions.length }}
        </span>
      </div>
      <button
        type="button"
        class="text-zinc-400 hover:text-zinc-200 p-1 rounded transition-colors"
        :disabled="loading"
        :title="t('ruleSuggestions.refresh')"
        @click="fetchSuggestions"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
      </button>
    </div>

    <!-- 错误或冲突提示 -->
    <div
      v-if="errorMsg"
      class="flex items-start gap-2 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs"
    >
      <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5 text-rose-400" />
      <span class="flex-1">{{ errorMsg }}</span>
    </div>

    <!-- 空状态 -->
    <div
      v-if="!loading && suggestions.length === 0"
      class="py-4 text-center text-xs text-zinc-500"
    >
      {{ t('ruleSuggestions.empty') }}
    </div>

    <!-- 建议列表 -->
    <div v-else class="space-y-2">
      <div
        v-for="s in suggestions"
        :key="s.id"
        class="p-2.5 rounded-lg bg-zinc-800/40 border border-zinc-700/60 flex flex-col gap-2"
      >
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5">
            <span class="text-xs px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-300 font-mono">
              {{ s.kind }}
            </span>
            <span class="text-xs text-zinc-400 font-mono truncate max-w-[200px]" :title="s.patch.path">
              {{ s.patch.path }}
            </span>
          </div>
          <span
            v-if="s.confidence"
            class="text-[11px] text-zinc-400"
          >
            {{ t('ruleSuggestions.confidence') }} {{ (s.confidence * 100).toFixed(0) }}%
          </span>
        </div>

        <!-- 差异对比 -->
        <div class="grid grid-cols-2 gap-2 text-xs font-mono bg-zinc-950/60 p-2 rounded border border-zinc-800">
          <div class="overflow-hidden">
            <div class="text-[10px] text-zinc-500 mb-0.5">{{ t('ruleSuggestions.currentConfig') }}</div>
            <div class="text-rose-400/90 truncate" :title="String(s.patch.old)">
              {{ s.patch.old !== undefined ? JSON.stringify(s.patch.old) : '-' }}
            </div>
          </div>
          <div class="overflow-hidden">
            <div class="text-[10px] text-zinc-500 mb-0.5">{{ t('ruleSuggestions.suggestedValue') }}</div>
            <div class="text-emerald-400 truncate" :title="String(s.patch.value)">
              {{ JSON.stringify(s.patch.value) }}
            </div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            class="px-2.5 py-1 text-xs rounded border border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600 transition-colors flex items-center gap-1"
            :disabled="actionLoading[s.id]"
            @click="handleDismiss(s)"
          >
            <X class="w-3 h-3" />
            <span>{{ t('ruleSuggestions.dismiss') }}</span>
          </button>
          <button
            type="button"
            class="px-2.5 py-1 text-xs rounded bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30 transition-colors flex items-center gap-1 font-medium"
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
