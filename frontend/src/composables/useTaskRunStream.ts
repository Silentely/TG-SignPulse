/**
 * 签到日志弹窗：WebSocket 实时流 + HTTP 轮询降级。
 */
import { ref, nextTick, computed, type Ref, type ComputedRef } from 'vue'
import {
  getSignTaskLogs,
  getSignTaskRunStatus,
} from '../lib/api'
import type { SignTaskRunStatus } from '../lib/api'
import { useAuthStore } from '../stores/auth'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import {
  badgeTone,
  badgeToneClass,
  phaseLabel,
  stateLabel,
} from '../lib/run-status'
import { useI18n } from './useI18n'

const POLL_INTERVAL_MS = 1500

export function useTaskRunStream(options: {
  taskName: ComputedRef<string>
  /** 解析后的账号名（用于 WS/轮询 query） */
  accountName: ComputedRef<string>
  /** 打开时若带 runAccount，视为本次执行中 */
  runAccount: ComputedRef<string | undefined>
  logContainer: Ref<HTMLElement | null>
}) {
  const { t } = useI18n()
  const authStore = useAuthStore()

  const realtimeLogs = ref<string[]>([])
  const isRunning = ref(false)
  const livePhase = ref<string | null>(null)
  const livePhaseDetail = ref('')
  const liveFailureCategory = ref<string | null>(null)
  const liveState = ref<string | null>(null)

  let ws: WebSocket | null = null
  let pollHandle: ChainPollHandle | null = null

  const applyStatusPayload = (msg: Record<string, unknown> | SignTaskRunStatus) => {
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

  const scrollLogToBottom = () => {
    nextTick(() => {
      if (options.logContainer.value) {
        options.logContainer.value.scrollTop = options.logContainer.value.scrollHeight
      }
    })
  }

  const stopPolling = () => {
    pollHandle?.stop()
    pollHandle = null
  }

  const startPolling = () => {
    if (pollHandle?.active) return
    pollHandle = startChainPoll(async () => {
      const name = options.taskName.value
      if (!name) return
      const token = authStore.token || ''
      const accountName = options.accountName.value || ''
      const [logsResult, statusResult] = await Promise.allSettled([
        getSignTaskLogs(token, name, accountName),
        getSignTaskRunStatus(token, name, accountName),
      ])
      if (!pollHandle?.active) return
      if (logsResult.status === 'fulfilled') {
        const data = logsResult.value
        if (Array.isArray(data) && data.length > 0) {
          realtimeLogs.value = data
          scrollLogToBottom()
        }
      }
      if (statusResult.status === 'fulfilled') {
        applyStatusPayload(statusResult.value)
        if (statusResult.value.state !== 'running') {
          isRunning.value = false
          stopPolling()
        }
      }
    }, { intervalMs: POLL_INTERVAL_MS })
  }

  const connect = () => {
    const name = options.taskName.value
    if (!name) return
    const token = authStore.token || ''
    const taskName = encodeURIComponent(name)
    const accountName = options.accountName.value || ''
    const runAccount = options.runAccount.value
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = window.location.host
    const wsUrl = `${wsProtocol}//${wsHost}/api/sign-tasks/ws/${taskName}?token=${encodeURIComponent(token)}&account_name=${encodeURIComponent(accountName)}`

    realtimeLogs.value = []
    isRunning.value = !!runAccount
    livePhase.value = runAccount ? 'starting' : null
    livePhaseDetail.value = ''
    liveFailureCategory.value = null
    liveState.value = runAccount ? 'running' : null

    try {
      ws = new WebSocket(wsUrl)
    } catch {
      if (runAccount) {
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
          scrollLogToBottom()
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
      if (options.runAccount.value) {
        isRunning.value = true
        startPolling()
      }
    }
    ws.onclose = () => {
      if (isRunning.value && options.runAccount.value) {
        startPolling()
      }
      ws = null
    }
  }

  const disconnect = () => {
    if (ws) {
      ws.close()
      ws = null
    }
    stopPolling()
    isRunning.value = false
    livePhase.value = null
    livePhaseDetail.value = ''
  }

  const resetLiveFailure = () => {
    liveFailureCategory.value = null
  }

  const clearLiveStatus = () => {
    livePhase.value = null
    livePhaseDetail.value = ''
    liveState.value = null
  }

  const clearRealtimeLogs = () => {
    realtimeLogs.value = []
  }

  return {
    realtimeLogs,
    isRunning,
    livePhase,
    livePhaseDetail,
    liveFailureCategory,
    liveState,
    liveStatusLabel,
    liveStatusToneClass,
    connect,
    disconnect,
    resetLiveFailure,
    clearLiveStatus,
    clearRealtimeLogs,
  }
}
