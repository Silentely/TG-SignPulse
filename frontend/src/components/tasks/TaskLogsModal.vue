<script setup lang="ts">
import { ref, watch, nextTick, computed } from 'vue'
import { Loader2, RefreshCw } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import FlowLogViewer from '../FlowLogViewer.vue'
import { getSignTaskHistory } from '../../lib/api'
import type { SignTaskHistoryItem } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
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
const livePhase = ref<string | null>(null)
const livePhaseDetail = ref('')
const liveFailureCategory = ref<string | null>(null)
const liveState = ref<string | null>(null)
let ws: WebSocket | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
const logContainer = ref<HTMLElement | null>(null)

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
    if (props.runAccount) {
      logs.value = []
      connectWebSocket()
    } else {
      livePhase.value = null
      livePhaseDetail.value = ''
      liveState.value = null
      loadLogs()
    }
  } else {
    logs.value = []
    realtimeLogs.value = []
    expandedIdx.value = null
    disconnectWebSocket()
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
          type="button"
          class="ui-icon-btn disabled:opacity-50"
          :disabled="loading"
          @click="loadLogs"
        >
          <RefreshCw class="w-4 h-4" :class="{'animate-spin': loading}" />
        </button>
      </div>
    </template>

    <div class="px-1 min-h-[400px] max-h-[60vh] overflow-y-auto flex flex-col">
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

          <!-- 摘要：最后返回 -->
          <div v-if="log.last_target_message || log.bot_message" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
            <div class="ui-section-label mb-1">{{ t('taskLogs.lastResponse') }}</div>
            <div class="whitespace-pre-wrap break-all p-2 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 text-xs">
              {{ log.last_target_message || log.bot_message }}
            </div>
          </div>

          <!-- 展开结构化详情 -->
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
    </div>
  </Modal>
</template>
