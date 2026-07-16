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
let ws: WebSocket | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
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
    console.error('Failed to fetch logs', e)
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
      if (msg.type === 'logs' && Array.isArray(msg.data)) {
        realtimeLogs.value.push(...msg.data)
        isRunning.value = msg.is_running !== false
        nextTick(() => {
          if (logContainer.value) {
            logContainer.value.scrollTop = logContainer.value.scrollHeight
          }
        })
      } else if (msg.type === 'done') {
        isRunning.value = false
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
}

watch(() => props.isOpen, (newVal) => {
  if (newVal) {
    expandedIdx.value = null
    if (props.runAccount) {
      logs.value = []
      connectWebSocket()
    } else {
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
      <div class="flex items-center gap-2">
        <span v-if="isRunning" class="flex items-center gap-1.5 text-xs text-blue-600 dark:text-blue-400">
          <span class="relative flex h-2 w-2">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-500 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
          </span>
          {{ t('taskLogs.running') }}
        </span>
        <button
          type="button"
          :disabled="loading"
          class="p-1.5 text-gray-500 hover:text-blue-500 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors disabled:opacity-50"
          @click="loadLogs"
        >
          <RefreshCw class="w-4 h-4" :class="{'animate-spin': loading}" />
        </button>
      </div>
    </template>

    <div class="px-1 min-h-[400px] max-h-[60vh] overflow-y-auto flex flex-col">
      <!-- Real-time logs -->
      <div v-if="realtimeLogs.length > 0 || isRunning" class="mb-4">
        <div class="text-xs font-medium text-gray-500 mb-2">{{ t('taskLogs.realtimeLogs') }}</div>
        <div
          ref="logContainer"
          class="p-3 bg-gray-950 rounded border border-gray-800 text-xs font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto"
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
      <div v-if="loading && logs.length === 0 && realtimeLogs.length === 0" class="flex items-center justify-center h-40">
        <Loader2 class="w-6 h-6 animate-spin text-gray-400" />
      </div>

      <div v-else-if="logs.length === 0 && realtimeLogs.length === 0 && !isRunning" class="flex flex-col items-center justify-center h-40 text-gray-400 text-sm">
        <span>{{ t('taskLogs.noLogs') }}</span>
      </div>

      <!-- History -->
      <div v-if="logs.length > 0" class="space-y-3">
        <div class="text-xs font-medium text-gray-500 mb-2">{{ t('taskLogs.history') }}</div>
        <div
          v-for="(log, idx) in logs"
          :key="idx"
          class="p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg border border-gray-100 dark:border-gray-800 text-sm"
        >
          <div class="flex items-center justify-between mb-2 gap-2">
            <span class="font-medium flex items-center gap-3 text-gray-900 dark:text-gray-200 flex-wrap">
              <span>{{ t('taskLogs.account') }}{{ log.account_name || t('taskLogs.unknown') }}</span>
              <span
                class="px-2 py-0.5 rounded text-xs border"
                :class="log.success
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50'
                  : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50'"
              >
                {{ log.success ? t('taskLogs.success') : t('taskLogs.failed') }}
              </span>
            </span>
            <span class="text-xs text-gray-500 font-mono shrink-0">{{ formatDate(log.time || log.created_at || '') }}</span>
          </div>

          <!-- 摘要：最后返回 -->
          <div v-if="log.last_target_message || log.bot_message" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
            <div class="font-semibold mb-1 text-xs text-gray-500">{{ t('taskLogs.lastResponse') }}</div>
            <div class="whitespace-pre-wrap break-all p-2 bg-white dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-700 text-xs">
              {{ log.last_target_message || log.bot_message }}
            </div>
          </div>

          <!-- 展开结构化详情 -->
          <div v-if="(log.flow_logs && log.flow_logs.length > 0) || log.message || log.summary" class="mt-3">
            <button
              type="button"
              class="text-xs text-blue-600 dark:text-blue-400 hover:underline mb-2"
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
