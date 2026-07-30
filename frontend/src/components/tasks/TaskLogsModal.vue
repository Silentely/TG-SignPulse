<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Download, RefreshCw } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import TaskLogsHitsPanel from './TaskLogsHitsPanel.vue'
import TaskLogsHistoryPanel from './TaskLogsHistoryPanel.vue'
import { getSignTaskHistory } from '../../lib/api'
import type { SignTaskHistoryItem, KeywordHitRecord } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useAuthStore } from '../../stores/auth'
import { useTaskHits } from '../../composables/useTaskHits'
import { useTaskRunStream } from '../../composables/useTaskRunStream'
import type { TaskUiItem } from '../../lib/types'
import { notifyApiError } from '../../lib/notify'
import { normalizeFlowLogLines } from '../../lib/task-log-format'
import { devLog } from '../../lib/devLog'
import { failureCategoryLabel } from '../../lib/run-status'

const { t } = useI18n()
const authStore = useAuthStore()

const props = defineProps<{
  isOpen: boolean
  task: TaskUiItem | null
  runAccount?: string  // Account selected for running (overrides task default)
  /** 打开时默认 Tab：history | hits（监听任务有效） */
  initialTab?: 'history' | 'hits' | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const logs = ref<SignTaskHistoryItem[]>([])
const loading = ref(false)
/** 监听任务：命中记录 Tab */
const panelTab = ref<'history' | 'hits'>('history')
const logContainer = ref<HTMLElement | null>(null)

/** 展开查看原始流日志的历史条目索引 */
const expandedIdx = ref<number | null>(null)

const getTaskAccountName = (task: TaskUiItem): string => {
  if (!task) return ''
  if (props.runAccount) return props.runAccount
  const raw = task.raw
  const name = raw.account_name || ''
  if (name && name !== '*') return name
  const names = raw.account_names || []
  for (const n of names) {
    if (n && n !== '*') return n
  }
  return ''
}

const lineTone = (text: string): string => {
  const s = text.toLowerCase()
  if (/失败|错误|exception|error|failed|traceback/.test(s)) return 'text-rose-400'
  if (/成功|完成|success|done|ok\b/.test(s)) return 'text-emerald-400'
  if (/警告|warning|warn|超时|timeout|retry|重试/.test(s)) return 'text-amber-400'
  return 'text-green-400'
}

const isListenTask = computed(() => props.task?.isListenMode || props.task?.raw?.execution_mode === 'listen')

const loadLogs = async () => {
  if (!props.task) return
  loading.value = true
  const token = authStore.token || ''
  try {
    const accountName = props.runAccount || getTaskAccountName(props.task) || undefined
    const res = await getSignTaskHistory(token, props.task.name, accountName)
    logs.value = Array.isArray(res) ? res : []
  } catch (e: unknown) {
    devLog.error('Failed to fetch logs', e)
    notifyApiError(e, 'logs.loadFailed')
    logs.value = []
  } finally {
    loading.value = false
  }
}

const taskNameRef = computed(() => props.task?.name || '')
const accountNameForHits = computed(() => (props.task ? (props.runAccount || getTaskAccountName(props.task) || undefined) : undefined))
const accountNameForStream = computed(() => (props.task ? getTaskAccountName(props.task) : ''))
const runAccountRef = computed(() => props.runAccount)
const isOpenRef = computed(() => props.isOpen)

const {
  hitsLoading,
  hitsLoadingMore,
  hitRecords,
  hitTotal,
  hitGroups,
  hitGroupBy,
  hitsView,
  canLoadMoreHits,
  loadHits,
  loadMoreHits,
  exportHits,
  clearHits,
  ensureHitsAutoRefresh,
  clearHitsAutoRefresh,
  resetHitsState,
} = useTaskHits({
  taskName: taskNameRef,
  accountName: accountNameForHits,
  isListenTask,
  isOpen: isOpenRef,
  panelTab,
})

const {
  realtimeLogs,
  isRunning,
  livePhase,
  livePhaseDetail,
  liveFailureCategory,
  liveState,
  liveStatusLabel,
  liveStatusToneClass,
  connect: connectWebSocket,
  disconnect: disconnectWebSocket,
  resetLiveFailure,
  clearLiveStatus,
  clearRealtimeLogs,
} = useTaskRunStream({
  taskName: taskNameRef,
  accountName: accountNameForStream,
  runAccount: runAccountRef,
  logContainer,
})

const displayRealtimeLines = computed(() => normalizeFlowLogLines(realtimeLogs.value))

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    expandedIdx.value = null
    resetLiveFailure()
    hitsView.value = 'list'
    hitGroupBy.value = 'chat'
    // 深链可直接打开命中 Tab
    const wantHits = props.initialTab === 'hits' && isListenTask.value
    panelTab.value = wantHits ? 'hits' : 'history'
    if (props.runAccount) {
      logs.value = []
      connectWebSocket()
    } else {
      clearLiveStatus()
      loadLogs()
    }
    if (isListenTask.value) {
      void loadHits()
      if (wantHits) ensureHitsAutoRefresh()
    }
  } else {
    logs.value = []
    clearRealtimeLogs()
    expandedIdx.value = null
    resetHitsState()
    disconnectWebSocket()
  }
})

watch([hitsView, hitGroupBy], () => {
  if (props.isOpen && isListenTask.value && panelTab.value === 'hits') {
    void loadHits()
  }
})

watch(panelTab, (tab) => {
  if (tab === 'hits' && props.isOpen && isListenTask.value) {
    void loadHits()
    ensureHitsAutoRefresh()
  } else {
    clearHitsAutoRefresh()
  }
})

const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  try {
    const d = new Date(dateStr)
    const mo = String(d.getMonth() + 1).padStart(2, '0')
    const da = String(d.getDate()).padStart(2, '0')
    const ho = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    const se = String(d.getSeconds()).padStart(2, '0')
    return `${mo}/${da} ${ho}:${mi}:${se}`
  } catch {
    return dateStr
  }
}

const toggleExpand = (idx: number) => {
  expandedIdx.value = expandedIdx.value === idx ? null : idx
}

/** 仅允许 http(s) 链接，避免 javascript: 等危险协议 */
const safeHitUrl = (url?: string | null): string | null => {
  const text = String(url || '').trim()
  if (!text) return null
  try {
    const parsed = new URL(text)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href
    }
  } catch {
    // ignore
  }
  return null
}

/** 列表项缓存安全 URL，避免模板重复解析 */
const hitLink = (hit: KeywordHitRecord) => safeHitUrl(hit.url)
</script>

<template>
  <Modal :isOpen="isOpen" @close="emit('close')" :title="t('taskLogs.title')" maxWidthClass="max-w-4xl">
    <template #header-extra>
      <div class="flex items-center gap-2 flex-wrap justify-end">
        <span
          v-if="isRunning || (liveState && liveState !== 'idle')"
          class="ui-badge !text-[11px] border max-w-[18rem] truncate"
          :class="liveStatusToneClass"
          :title="liveStatusLabel"
        >
          <span v-if="isRunning" class="ui-pulse-dot !bg-sky-500" />
          {{ liveStatusLabel }}
        </span>
        <span
          v-if="liveFailureCategory && !isRunning"
          class="ui-badge ui-badge-error !text-[11px]"
        >
          {{ failureCategoryLabel(liveFailureCategory, t) }}
        </span>
        <button
          v-if="panelTab === 'hits'"
          type="button"
          class="ui-icon-btn disabled:opacity-50"
          :title="t('taskLogs.hitsExport')"
          @click="exportHits"
        >
          <Download class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="ui-icon-btn disabled:opacity-50"
          :disabled="panelTab === 'history' ? loading : hitsLoading"
          @click="panelTab === 'history' ? loadLogs() : loadHits()"
        >
          <RefreshCw class="w-4 h-4" :class="{'animate-spin': panelTab === 'history' ? loading : hitsLoading}" />
        </button>
      </div>
    </template>

    <div class="px-1 min-h-[400px] max-h-[60vh] overflow-y-auto flex flex-col">
      <!-- 监听任务：历史 / 命中 Tab -->
      <div v-if="isListenTask" class="mb-3 flex flex-wrap items-center gap-1 border-b border-gray-100 dark:border-gray-800/60 pb-2">
        <button
          type="button"
          class="px-2.5 py-1 text-xs rounded-sm transition-colors"
          :class="panelTab === 'history'
            ? 'bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
            : 'text-gray-500 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
          @click="panelTab = 'history'"
        >
          {{ t('taskLogs.history') }}
        </button>
        <button
          type="button"
          class="px-2.5 py-1 text-xs rounded-sm transition-colors"
          :class="panelTab === 'hits'
            ? 'bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
            : 'text-gray-500 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
          @click="panelTab = 'hits'; loadHits()"
        >
          {{ t('taskLogs.hitsTab') }}
          <span v-if="hitTotal" class="ml-1 font-mono opacity-80">{{ hitTotal }}</span>
        </button>
      </div>

      <TaskLogsHitsPanel
        v-if="panelTab === 'hits' && isListenTask"
        :hits-loading="hitsLoading"
        :hits-loading-more="hitsLoadingMore"
        :hits-view="hitsView"
        :hit-group-by="hitGroupBy"
        :hit-records="hitRecords"
        :hit-groups="hitGroups"
        :hit-total="hitTotal"
        :can-load-more-hits="canLoadMoreHits"
        :format-date="formatDate"
        :hit-link="hitLink"
        @update:hits-view="hitsView = $event"
        @update:hit-group-by="hitGroupBy = $event"
        @clear-hits="clearHits"
        @load-more="loadMoreHits"
      />

      <TaskLogsHistoryPanel
        v-else
        :run-account="runAccount"
        :is-running="isRunning"
        :live-phase="livePhase"
        :live-phase-detail="livePhaseDetail"
        :live-state="liveState"
        :live-status-label="liveStatusLabel"
        :live-status-tone-class="liveStatusToneClass"
        :realtime-logs="realtimeLogs"
        :display-realtime-lines="displayRealtimeLines"
        :loading="loading"
        :logs="logs"
        :expanded-idx="expandedIdx"
        :format-date="formatDate"
        :line-tone="lineTone"
        @toggle-expand="toggleExpand"
        @set-log-container="logContainer = $event"
      />
    </div>
  </Modal>
</template>
