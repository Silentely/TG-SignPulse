<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { Download, Loader2, RefreshCw } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import FlowLogViewer from '../FlowLogViewer.vue'
import {
  getSignTaskHistory,
  listKeywordHits,
  listKeywordHitGroups,
  exportKeywordHitsUrl,
  clearKeywordHits,
} from '../../lib/api'
import type { SignTaskHistoryItem, KeywordHitRecord, KeywordHitGroup } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
import { useAuthStore } from '../../stores/auth'
import type { TaskUiItem } from '../../lib/types'
import { getLocalizedErrorMessage } from '../../lib/types'
import { normalizeFlowLogLines } from '../../lib/task-log-format'
import { devLog } from '../../lib/devLog'
import {
  badgeTone,
  badgeToneClass,
  failureCategoryLabel,
  formatPhaseDetail,
  phaseLabel,
  stateLabel,
} from '../../lib/run-status'

const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()

const props = defineProps<{
  isOpen: boolean
  task: TaskUiItem | null
  runAccount?: string  // Account selected for running (overrides task default)
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const logs = ref<SignTaskHistoryItem[]>([])
const realtimeLogs = ref<string[]>([])
const loading = ref(false)
const isRunning = ref(false)
/** 监听任务：命中记录 Tab */
const panelTab = ref<'history' | 'hits'>('history')
const hitsLoading = ref(false)
const hitsLoadingMore = ref(false)
const hitRecords = ref<KeywordHitRecord[]>([])
const hitTotal = ref(0)
const hitGroups = ref<KeywordHitGroup[]>([])
const hitGroupBy = ref<'task' | 'account' | 'chat'>('chat')
const hitsView = ref<'list' | 'groups'>('list')
const HITS_PAGE_SIZE = 50
const livePhase = ref<string | null>(null)
const livePhaseDetail = ref('')
const liveFailureCategory = ref<string | null>(null)
const liveState = ref<string | null>(null)
let ws: WebSocket | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let hitsAutoRefreshTimer: ReturnType<typeof setInterval> | null = null
const logContainer = ref<HTMLElement | null>(null)
const canLoadMoreHits = computed(
  () => hitsView.value === 'list' && hitRecords.value.length < hitTotal.value,
)

const applyStatusPayload = (msg: Record<string, unknown>) => {
  if (msg.phase !== undefined) livePhase.value = (msg.phase as string) || null
  if (msg.phase_detail !== undefined) livePhaseDetail.value = String(msg.phase_detail || '')
  if (msg.failure_category !== undefined) {
    liveFailureCategory.value = (msg.failure_category as string) || null
  }
  if (msg.state !== undefined) liveState.value = (msg.state as string) || null
}

const liveStatusLabel = computed(() => {
  if (livePhaseDetail.value) return livePhaseDetail.value
  if (livePhase.value) return phaseLabel(livePhase.value, t)
  if (liveState.value && liveState.value !== 'running') return stateLabel(liveState.value, t)
  return t('taskLogs.running')
})

const liveStatusToneClass = computed(() =>
  badgeToneClass(
    badgeTone({
      state: liveState.value || (isRunning.value ? 'running' : 'finished'),
      phase: livePhase.value,
      success: liveState.value === 'finished' ? true : liveState.value === 'timeout' ? false : null,
      failure_category: liveFailureCategory.value,
    }),
  ),
)

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

const displayRealtimeLines = computed(() => normalizeFlowLogLines(realtimeLogs.value))

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
    toast.error(getLocalizedErrorMessage(e, t, t('logs.loadFailed')))
    logs.value = []
  } finally {
    loading.value = false
  }
}

const clearHitsAutoRefresh = () => {
  if (hitsAutoRefreshTimer) {
    clearInterval(hitsAutoRefreshTimer)
    hitsAutoRefreshTimer = null
  }
}

const ensureHitsAutoRefresh = () => {
  clearHitsAutoRefresh()
  if (!props.isOpen || !isListenTask.value || panelTab.value !== 'hits') return
  // 监听任务打开命中 Tab 时静默刷新，便于观察新命中
  hitsAutoRefreshTimer = setInterval(() => {
    void loadHits({ silent: true })
  }, 8000)
}

const loadHits = async (opts?: { silent?: boolean; append?: boolean }) => {
  if (!props.task) return
  const silent = !!opts?.silent
  const append = !!opts?.append && hitsView.value === 'list'
  if (append) {
    if (hitsLoadingMore.value || !canLoadMoreHits.value) return
    hitsLoadingMore.value = true
  } else if (!silent) {
    hitsLoading.value = true
  }
  const token = authStore.token || ''
  const accountName = props.runAccount || getTaskAccountName(props.task) || undefined
  try {
    if (hitsView.value === 'groups') {
      const res = await listKeywordHitGroups(token, {
        account_name: accountName,
        task_name: props.task.name,
        group_by: hitGroupBy.value,
        limit_per_group: 30,
      })
      hitGroups.value = res.groups || []
      hitTotal.value = hitGroups.value.reduce((sum, g) => sum + (g.count || 0), 0)
      hitRecords.value = []
    } else {
      const offset = append ? hitRecords.value.length : 0
      const res = await listKeywordHits(token, {
        account_name: accountName,
        task_name: props.task.name,
        limit: HITS_PAGE_SIZE,
        offset,
      })
      const items = res.items || []
      if (append) {
        // 按 id 去重拼接
        const seen = new Set(hitRecords.value.map((h) => h.id))
        hitRecords.value = [
          ...hitRecords.value,
          ...items.filter((h) => h.id && !seen.has(h.id)),
        ]
      } else if (silent && hitRecords.value.length > 0) {
        // 静默刷新：合并新记录到顶部，保留已加载更多
        const existingIds = new Set(hitRecords.value.map((h) => h.id))
        const fresh = items.filter((h) => h.id && !existingIds.has(h.id))
        if (fresh.length) {
          hitRecords.value = [...fresh, ...hitRecords.value]
        } else {
          // 无新记录时更新首页重叠部分的字段
          const byId = new Map(items.map((h) => [h.id, h]))
          hitRecords.value = hitRecords.value.map((h) => byId.get(h.id) || h)
        }
      } else {
        hitRecords.value = items
      }
      hitTotal.value = res.total || 0
      hitGroups.value = []
    }
  } catch (e: unknown) {
    devLog.error('Failed to fetch keyword hits', e)
    if (!silent) {
      toast.error(getLocalizedErrorMessage(e, t, t('taskLogs.hitsLoadFailed')))
      if (!append) {
        hitRecords.value = []
        hitGroups.value = []
        hitTotal.value = 0
      }
    }
  } finally {
    hitsLoading.value = false
    hitsLoadingMore.value = false
  }
}

const loadMoreHits = () => loadHits({ append: true })

const exportHits = async () => {
  if (!props.task) return
  const token = authStore.token || ''
  const accountName = props.runAccount || getTaskAccountName(props.task) || undefined
  const url = exportKeywordHitsUrl({
    account_name: accountName,
    task_name: props.task.name,
    limit: 2000,
  })
  try {
    const res = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) throw new Error(`export failed: ${res.status}`)
    const blob = await res.blob()
    const a = document.createElement('a')
    const objectUrl = URL.createObjectURL(blob)
    a.href = objectUrl
    a.download = `keyword_hits_${props.task.name}.csv`
    a.click()
    URL.revokeObjectURL(objectUrl)
    toast.success(t('taskLogs.hitsExportDone'))
  } catch (e: unknown) {
    toast.error(getLocalizedErrorMessage(e, t, t('taskLogs.hitsExportFailed')))
  }
}

const clearHits = async () => {
  if (!props.task) return
  const ok = await confirm({
    title: t('common.dangerConfirm'),
    message: t('taskLogs.hitsClearConfirm'),
    confirmText: t('common.delete'),
    danger: true,
  })
  if (!ok) return
  const token = authStore.token || ''
  const accountName = props.runAccount || getTaskAccountName(props.task) || undefined
  try {
    const res = await clearKeywordHits(token, {
      account_name: accountName,
      task_name: props.task.name,
    })
    toast.success(t('taskLogs.hitsCleared', { n: res.deleted ?? 0 }))
    await loadHits()
  } catch (e: unknown) {
    toast.error(getLocalizedErrorMessage(e, t, t('taskLogs.hitsClearFailed')))
  }
}

const connectWebSocket = () => {
  if (!props.task) return
  const token = authStore.token || ''
  const taskName = encodeURIComponent(props.task.name)
  const accountName = getTaskAccountName(props.task) || ''
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsHost = window.location.host
  const wsUrl = `${wsProtocol}//${wsHost}/api/sign-tasks/ws/${taskName}?token=${encodeURIComponent(token)}&account_name=${encodeURIComponent(accountName)}`

  realtimeLogs.value = []
  isRunning.value = !!props.runAccount
  livePhase.value = props.runAccount ? 'starting' : null
  livePhaseDetail.value = ''
  liveFailureCategory.value = null
  liveState.value = props.runAccount ? 'running' : null

  try {
    ws = new WebSocket(wsUrl)
  } catch {
    if (props.runAccount) {
      isRunning.value = false
      startPolling()
    }
    return
  }

  ws.onopen = () => {
    // Connected successfully
  }
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      applyStatusPayload(msg)
      if (msg.type === 'logs' && Array.isArray(msg.data)) {
        realtimeLogs.value.push(...msg.data)
        isRunning.value = msg.is_running !== false
        nextTick(() => {
          if (logContainer.value) {
            logContainer.value.scrollTop = logContainer.value.scrollHeight
          }
        })
      } else if (msg.type === 'status') {
        isRunning.value = msg.is_running !== false
      } else if (msg.type === 'done') {
        isRunning.value = false
        if (!liveState.value || liveState.value === 'running') {
          liveState.value = msg.state || 'finished'
        }
      }
    } catch {
      // ignore malformed frames
    }
  }
  ws.onerror = () => {
    if (props.runAccount) {
      isRunning.value = true
      startPolling()
    }
  }
  ws.onclose = () => {
    if (isRunning.value && props.runAccount) {
      startPolling()
    }
    ws = null
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!props.task) return
    const token = authStore.token || ''
    const accountName = getTaskAccountName(props.task) || ''
    try {
      const res = await fetch(`/api/sign-tasks/${encodeURIComponent(props.task.name)}/logs?account_name=${encodeURIComponent(accountName)}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data) && data.length > 0) {
          realtimeLogs.value = data
          nextTick(() => {
            if (logContainer.value) {
              logContainer.value.scrollTop = logContainer.value.scrollHeight
            }
          })
        }
      }
      const statusRes = await fetch(`/api/sign-tasks/${encodeURIComponent(props.task.name)}/run/status?account_name=${encodeURIComponent(accountName)}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (statusRes.ok) {
        const status = await statusRes.json()
        applyStatusPayload(status)
        if (status.state !== 'running') {
          isRunning.value = false
          if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
        }
      }
    } catch {
      // keep polling
    }
  }, 1500)
}

const disconnectWebSocket = () => {
  if (ws) {
    ws.close()
    ws = null
  }
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  isRunning.value = false
  livePhase.value = null
  livePhaseDetail.value = ''
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    expandedIdx.value = null
    liveFailureCategory.value = null
    panelTab.value = 'history'
    hitsView.value = 'list'
    hitGroupBy.value = 'chat'
    if (props.runAccount) {
      logs.value = []
      connectWebSocket()
    } else {
      livePhase.value = null
      livePhaseDetail.value = ''
      liveState.value = null
      loadLogs()
    }
    if (isListenTask.value) {
      void loadHits()
    }
  } else {
    logs.value = []
    realtimeLogs.value = []
    hitRecords.value = []
    hitGroups.value = []
    hitTotal.value = 0
    expandedIdx.value = null
    clearHitsAutoRefresh()
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

      <template v-if="panelTab === 'hits' && isListenTask">
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <div class="flex items-center gap-1 text-[11px]">
            <button
              type="button"
              class="px-2 py-1 rounded-sm border"
              :class="hitsView === 'list' ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-gray-200 dark:border-gray-700 text-gray-500'"
              @click="hitsView = 'list'"
            >
              {{ t('taskLogs.hitsList') }}
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded-sm border"
              :class="hitsView === 'groups' ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-gray-200 dark:border-gray-700 text-gray-500'"
              @click="hitsView = 'groups'"
            >
              {{ t('taskLogs.hitsGroups') }}
            </button>
          </div>
          <select
            v-if="hitsView === 'groups'"
            v-model="hitGroupBy"
            class="ui-input !h-8 !text-xs !w-auto"
          >
            <option value="chat">{{ t('taskLogs.groupByChat') }}</option>
            <option value="account">{{ t('taskLogs.groupByAccount') }}</option>
            <option value="task">{{ t('taskLogs.groupByTask') }}</option>
          </select>
          <span class="text-[10px] text-gray-400 hidden md:inline">{{ t('taskLogs.hitsAutoRefreshHint') }}</span>
          <button
            type="button"
            class="ml-auto text-[11px] text-rose-600 dark:text-rose-400 hover:underline"
            @click="clearHits"
          >
            {{ t('taskLogs.hitsClear') }}
          </button>
        </div>

        <div v-if="hitsLoading" class="ui-page-loading !py-10">
          <div class="ui-spinner" />
        </div>
        <div v-else-if="hitsView === 'list' && hitRecords.length === 0" class="ui-empty !py-10">
          <p class="ui-empty-desc">{{ t('taskLogs.hitsEmpty') }}</p>
        </div>
        <div v-else-if="hitsView === 'groups' && hitGroups.length === 0" class="ui-empty !py-10">
          <p class="ui-empty-desc">{{ t('taskLogs.hitsEmpty') }}</p>
        </div>

        <div v-else-if="hitsView === 'list'" class="space-y-2">
          <div
            v-for="hit in hitRecords"
            :key="hit.id"
            class="ui-card p-3 text-xs space-y-1.5"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono text-sky-700 dark:text-sky-300 truncate">{{ hit.keyword || '-' }}</span>
              <span class="text-gray-500 font-mono shrink-0">{{ formatDate(hit.time) }}</span>
            </div>
            <div class="text-gray-600 dark:text-gray-400 truncate">
              {{ hit.chat_title || hit.chat_id || '-' }}
              <span v-if="hit.sender" class="text-gray-400"> · {{ hit.sender }}</span>
              <span v-if="hit.push_channel" class="text-gray-400"> · {{ hit.push_channel }}</span>
            </div>
            <div class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all line-clamp-3">
              {{ hit.message_text || '-' }}
            </div>
            <template v-if="hitLink(hit)">
              <a
                :href="hitLink(hit)!"
                target="_blank"
                rel="noopener noreferrer"
                class="text-sky-600 dark:text-sky-400 hover:underline"
              >{{ t('taskLogs.hitsOpenMessage') }}</a>
            </template>
          </div>
          <div v-if="canLoadMoreHits" class="pt-1 flex justify-center">
            <button
              type="button"
              class="ui-btn-secondary !px-3 !py-1.5 !text-xs"
              :disabled="hitsLoadingMore"
              @click="loadMoreHits"
            >
              <span v-if="hitsLoadingMore" class="ui-spinner !w-3 !h-3 !border-2 mr-1" />
              {{ t('taskLogs.hitsLoadMore') }}
              <span class="font-mono opacity-70 ml-1">({{ hitRecords.length }}/{{ hitTotal }})</span>
            </button>
          </div>
        </div>

        <div v-else class="space-y-3">
          <div
            v-for="group in hitGroups"
            :key="group.key"
            class="ui-card p-3 space-y-2"
          >
            <div class="flex items-center justify-between gap-2 text-xs">
              <span class="font-medium text-gray-900 dark:text-gray-100 truncate">{{ group.label }}</span>
              <span class="ui-badge ui-badge-neutral !text-[11px] font-mono">{{ group.count }}</span>
            </div>
            <div class="space-y-1.5 border-t border-gray-100 dark:border-gray-800/50 pt-2">
              <div
                v-for="hit in group.items"
                :key="hit.id"
                class="text-[11px] flex items-start justify-between gap-2"
              >
                <div class="min-w-0">
                  <span class="font-mono text-sky-700 dark:text-sky-300">{{ hit.keyword || '-' }}</span>
                  <span class="text-gray-500 ml-1 truncate">{{ hit.message_text || '' }}</span>
                </div>
                <span class="text-gray-400 font-mono shrink-0">{{ formatDate(hit.time) }}</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <template v-else>
        <!-- 运行 phase 状态条（实时） -->
        <div
          v-if="runAccount && (isRunning || livePhaseDetail || livePhase)"
          class="mb-3 px-3 py-2 rounded-sm border text-xs flex flex-wrap items-center gap-2"
          :class="liveStatusToneClass"
        >
          <span class="font-medium">{{ formatPhaseDetail({ phase: livePhase, phase_detail: livePhaseDetail }, t) || liveStatusLabel }}</span>
          <span v-if="liveState && liveState !== 'running'" class="opacity-80">· {{ stateLabel(liveState, t) }}</span>
        </div>

        <!-- Real-time logs -->
        <div v-if="realtimeLogs.length > 0 || isRunning" class="mb-4">
          <div class="ui-section-label mb-2">{{ t('taskLogs.realtimeLogs') }}</div>
          <div
            ref="logContainer"
            class="ui-terminal whitespace-pre-wrap break-all !max-h-60"
          >
            <div
              v-for="(line, i) in (displayRealtimeLines.length ? displayRealtimeLines : realtimeLogs)"
              :key="i"
              class="leading-relaxed"
              :class="lineTone(String(line))"
            >
              {{ line }}
            </div>
            <div v-if="isRunning && realtimeLogs.length === 0" class="text-gray-500 flex items-center gap-2">
              <Loader2 class="w-3 h-3 animate-spin" /> {{ t('taskLogs.waitingOutput') }}
            </div>
          </div>
        </div>

        <!-- Loading / empty -->
        <div v-if="loading && logs.length === 0 && realtimeLogs.length === 0" class="ui-page-loading !py-10">
          <div class="ui-spinner" />
        </div>

        <div v-else-if="logs.length === 0 && realtimeLogs.length === 0 && !isRunning" class="ui-empty !py-10">
          <p class="ui-empty-desc">{{ t('taskLogs.noLogs') }}</p>
        </div>

        <!-- History -->
        <div v-if="logs.length > 0" class="space-y-3">
          <div class="ui-section-label mb-2">{{ t('taskLogs.history') }}</div>
          <div
            v-for="(log, idx) in logs"
            :key="idx"
            class="ui-card p-3 text-sm"
          >
            <div class="flex items-center justify-between mb-2 gap-2">
              <span class="font-medium flex items-center gap-3 text-gray-900 dark:text-gray-200 flex-wrap">
                <span>{{ t('taskLogs.account') }}{{ log.account_name || t('taskLogs.unknown') }}</span>
                <span
                  class="ui-badge"
                  :class="log.success ? 'ui-badge-success' : 'ui-badge-error'"
                >
                  <span class="ui-badge-dot" />
                  {{ log.success ? t('taskLogs.success') : t('taskLogs.failed') }}
                </span>
              </span>
              <span class="text-xs text-gray-500 font-mono shrink-0">{{ formatDate(log.time || log.created_at || '') }}</span>
            </div>

            <div v-if="log.last_target_message || log.bot_message" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
              <div class="ui-section-label mb-1">{{ t('taskLogs.lastResponse') }}</div>
              <div class="whitespace-pre-wrap break-all p-2 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 text-xs">
                {{ log.last_target_message || log.bot_message }}
              </div>
            </div>

            <div v-if="(log.flow_logs && log.flow_logs.length > 0) || log.message || log.summary" class="mt-3">
              <button
                type="button"
                class="text-xs text-sky-600 dark:text-sky-400 hover:underline mb-2"
                @click="toggleExpand(idx)"
              >
                {{ expandedIdx === idx ? t('taskLogs.collapseDetail') : t('taskLogs.expandDetail') }}
              </button>
              <FlowLogViewer
                v-if="expandedIdx === idx"
                :lines="log.flow_logs || (log.message || log.summary ? [String(log.message || log.summary)] : [])"
                :last-target-message="log.last_target_message || log.bot_message"
                :truncated="!!log.flow_truncated"
                compact
              />
            </div>
          </div>
        </div>
      </template>
    </div>
  </Modal>
</template>
