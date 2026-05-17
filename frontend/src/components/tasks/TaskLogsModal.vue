<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { Loader2, RefreshCw } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import { getSignTaskHistory } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  isOpen: boolean
  task: any | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const logs = ref<any[]>([])
const realtimeLogs = ref<string[]>([])
const loading = ref(false)
const isRunning = ref(false)
let ws: WebSocket | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
const logContainer = ref<HTMLElement | null>(null)

const getTaskAccountName = (task: any): string => {
  if (!task) return ''
  const name = task.raw?.account_name || task.account_name || ''
  if (name) return name
  const names = task.raw?.account_names || task.account_names || []
  if (names.length > 0) {
    // Skip wildcard '*', use first real account name
    const realName = names.find((n: string) => n && n !== '*')
    return realName || ''
  }
  return ''
}

const loadLogs = async () => {
  if (!props.task) return
  loading.value = true
  const token = localStorage.getItem('tg-signer-token') || ''
  try {
    // Use getTaskAccountName to properly resolve account, pass undefined if empty to let backend aggregate
    const accountName = getTaskAccountName(props.task) || undefined
    const res = await getSignTaskHistory(token, props.task.name, accountName)
    logs.value = Array.isArray(res) ? res : ((res as any).data || [])
  } catch (e) {
    console.error('Failed to fetch logs', e)
    logs.value = []
  } finally {
    loading.value = false
  }
}

const connectWebSocket = () => {
  if (!props.task) return
  const token = localStorage.getItem('tg-signer-token') || ''
  const taskName = encodeURIComponent(props.task.name)
  const accountName = getTaskAccountName(props.task) || ''
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsHost = window.location.host
  const wsUrl = `${wsProtocol}//${wsHost}/api/sign-tasks/ws/${taskName}?token=${encodeURIComponent(token)}&account_name=${encodeURIComponent(accountName)}`

  realtimeLogs.value = []
  isRunning.value = true

  try {
    ws = new WebSocket(wsUrl)
  } catch {
    // WebSocket not available, fall back to polling
    isRunning.value = false
    startPolling()
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
        setTimeout(loadLogs, 1000)
      }
    } catch {}
  }
  ws.onerror = () => {
    // WebSocket failed, fall back to polling
    isRunning.value = true
    startPolling()
  }
  ws.onclose = () => {
    if (isRunning.value) {
      // Unexpected close while running, try polling
      startPolling()
    }
    ws = null
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    if (!props.task) return
    const token = localStorage.getItem('tg-signer-token') || ''
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
      // Check if task is still running
      const statusRes = await fetch(`/api/sign-tasks/${encodeURIComponent(props.task.name)}/run/status?account_name=${encodeURIComponent(accountName)}`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      if (statusRes.ok) {
        const status = await statusRes.json()
        if (status.state !== 'running') {
          isRunning.value = false
          if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
          setTimeout(loadLogs, 1000)
        }
      }
    } catch {}
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
    loadLogs()
    // Try to connect WebSocket for real-time logs
    connectWebSocket()
  } else {
    logs.value = []
    realtimeLogs.value = []
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
  } catch (e) {
    return dateStr
  }
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
        <button @click="loadLogs" :disabled="loading" class="p-1.5 text-gray-500 hover:text-blue-500 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors disabled:opacity-50">
          <RefreshCw class="w-4 h-4" :class="{'animate-spin': loading}" />
        </button>
      </div>
    </template>

    <div class="px-1 min-h-[400px] max-h-[60vh] overflow-y-auto flex flex-col">
      <!-- Real-time logs section -->
      <div v-if="realtimeLogs.length > 0 || isRunning" class="mb-4">
        <div class="text-xs font-medium text-gray-500 mb-2">{{ t('taskLogs.realtimeLogs') }}</div>
        <div ref="logContainer" class="p-3 bg-gray-950 text-green-400 rounded border border-gray-800 text-xs font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto">
          <div v-for="(line, i) in realtimeLogs" :key="i" class="leading-relaxed">{{ line }}</div>
          <div v-if="isRunning && realtimeLogs.length === 0" class="text-gray-500 flex items-center gap-2">
            <Loader2 class="w-3 h-3 animate-spin" /> {{ t('taskLogs.waitingOutput') }}
          </div>
        </div>
      </div>

      <!-- History logs section -->
      <div v-if="loading && logs.length === 0 && realtimeLogs.length === 0" class="flex items-center justify-center h-40">
        <Loader2 class="w-6 h-6 animate-spin text-gray-400" />
      </div>
      
      <div v-else-if="logs.length === 0 && realtimeLogs.length === 0 && !isRunning" class="flex flex-col items-center justify-center h-40 text-gray-400 text-sm">
        <span>{{ t('taskLogs.noLogs') }}</span>
      </div>

      <div v-if="logs.length > 0" class="space-y-3">
        <div class="text-xs font-medium text-gray-500 mb-2">{{ t('taskLogs.history') }}</div>
        <div v-for="(log, idx) in logs" :key="idx" class="p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg border border-gray-100 dark:border-gray-800 text-sm">
          <div class="flex items-center justify-between mb-2">
            <span class="font-medium flex items-center gap-4 text-gray-900 dark:text-gray-200">
              <span>{{ t('taskLogs.account') }}{{ log.account_name || t('taskLogs.unknown') }}</span>
              <span class="px-2 py-0.5 rounded text-xs border"
                    :class="log.success ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50' : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50'">
                {{ log.success ? t('taskLogs.success') : t('taskLogs.failed') }}
              </span>
            </span>
            <span class="text-xs text-gray-500">{{ formatDate(log.time || log.created_at) }}</span>
          </div>

          <div v-if="log.last_target_message || log.bot_message" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
            <div class="font-semibold mb-1">{{ t('taskLogs.lastResponse') }}</div>
            <div class="whitespace-pre-wrap break-all p-2 bg-white dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-700 text-xs">{{ log.last_target_message || log.bot_message }}</div>
          </div>
          
          <div v-if="log.flow_logs && log.flow_logs.length > 0" class="mt-3">
            <div class="font-semibold text-sm mb-1 text-gray-700 dark:text-gray-300">{{ t('taskLogs.logDetail') }}</div>
            <div class="p-2 bg-gray-900 text-gray-300 rounded border border-gray-700 text-xs font-mono whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
              <div v-for="(line, i) in log.flow_logs" :key="i">{{ line }}</div>
              <div v-if="log.flow_truncated" class="text-gray-500 italic mt-1">{{ t('taskLogs.truncated') }}</div>
            </div>
          </div>
          <div v-else-if="log.message || log.summary" class="mt-3 text-sm text-gray-700 dark:text-gray-300">
            <div class="font-semibold mb-1">{{ t('taskLogs.logDetail') }}</div>
            <div class="p-2 bg-gray-900 text-gray-300 rounded border border-gray-700 text-xs font-mono whitespace-pre-wrap break-all max-h-40 overflow-y-auto">{{ log.message || log.summary }}</div>
          </div>
        </div>
      </div>
    </div>
  </Modal>
</template>
