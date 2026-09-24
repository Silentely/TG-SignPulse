/**
 * 签到日志弹窗：WebSocket 实时流 + HTTP 轮询降级。
 */
import { ref, nextTick, computed, type Ref, type ComputedRef } from 'vue'
import {
  getSignTaskLogs,
  getSignTaskRunStatus,
  issueStreamTicket,
  STREAM_TICKET_PURPOSE,
} from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import type { SignTaskRunStatus } from '../lib/api'
import { devLog } from '../lib/devLog'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import {
  badgeTone,
  badgeToneClass,
  phaseLabel,
  stateLabel,
} from '../lib/run-status'
import { useI18n } from './useI18n'

const POLL_INTERVAL_MS = 1500
// WS 实时日志行上限：长时运行任务只增不减会攒数千行字符串+DOM 节点；
// 截尾与轮询降级分支（整体替换、天然有界）的语义对齐
const MAX_REALTIME_LOG_LINES = 1000

export function useTaskRunStream(options: {
  taskName: ComputedRef<string>
  /** 解析后的账号名（用于 WS/轮询 query） */
  accountName: ComputedRef<string>
  /** 打开时若带 runAccount，视为本次执行中 */
  runAccount: ComputedRef<string | undefined>
  logContainer: Ref<HTMLElement | null>
}) {
  const { t } = useI18n()

  const realtimeLogs = ref<string[]>([])
  const isRunning = ref(false)
  const livePhase = ref<string | null>(null)
  const livePhaseDetail = ref('')
  const liveFailureCategory = ref<string | null>(null)
  const liveState = ref<string | null>(null)

  let ws: WebSocket | null = null
  let pollHandle: ChainPollHandle | null = null

  // 连接世代：connect 在换票 await 期间可被更新的 connect / disconnect 取代。
  // 换票返回后必须核对世代，旧一代直接放弃建连，避免关闭或切换任务后
  // 仍开出孤儿 WebSocket，令日志重复、isRunning 被错误复活。
  let connectGeneration = 0

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
      // 弹窗开着但标签页切后台时不发请求；WS 连接保留，恢复可见由
      // 浏览器节流解除后继续（无独立心跳需求）
      if (typeof document !== 'undefined' && document.hidden) return
      const name = options.taskName.value
      if (!name) return
      const token = getAuthToken()
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

  const connect = async () => {
    const name = options.taskName.value
    if (!name) return
    const gen = ++connectGeneration
    if (ws) {
      const socket = ws
      ws = null
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      socket.close()
    }
    stopPolling()

    const taskName = encodeURIComponent(name)
    const accountName = options.accountName.value || ''
    const runAccount = options.runAccount.value
    // WebSocket 无法带 Authorization 头：先用 Bearer JWT 换一次性票据，
    // 避免长效 JWT 出现在 URL 里（会被访问日志 / 反代日志 / 浏览器历史记录）。
    // 换票失败时退化为纯轮询，与建连抛异常的分支保持一致。
    let ticket: string
    try {
      const res = await issueStreamTicket(STREAM_TICKET_PURPOSE.taskRunWs, name)
      // 换票期间可能已被 disconnect 或更新的 connect 取代，弃票返回
      if (gen !== connectGeneration) return
      ticket = res.ticket
    } catch (e: unknown) {
      devLog.error('issue WS ticket failed', e)
      // 仅当本次仍是最新一次调用时才退化为轮询，避免旧调用接管当前状态
      if (gen === connectGeneration && runAccount) {
        isRunning.value = false
        startPolling()
      }
      return
    }
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsHost = window.location.host
    const wsUrl = `${wsProtocol}//${wsHost}/api/sign-tasks/ws/${taskName}?ticket=${encodeURIComponent(ticket)}&account_name=${encodeURIComponent(accountName)}`

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
      devLog.info('任务日志 WebSocket 已连接:', wsUrl)
    }
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        applyStatusPayload(msg)
        if (msg.type === 'logs' && Array.isArray(msg.data)) {
          realtimeLogs.value.push(...msg.data)
          const overflow = realtimeLogs.value.length - MAX_REALTIME_LOG_LINES
          if (overflow > 0) realtimeLogs.value.splice(0, overflow)
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
    // 失效在途 connect：换票返回后不会再建连
    connectGeneration += 1
    if (ws) {
      const socket = ws
      ws = null
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      socket.close()
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
