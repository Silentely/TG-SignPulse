/**
 * 仪表盘：统计/日志/活跃 run 拉取 + 签到历史 SSE。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import {
  listAccounts,
  listSignTasks,
  getRecentAccountLogs,
  listScheduledJobs,
  listActiveSignTaskRuns,
  listKeywordHits,
  listAccountStatusCheckJobs,
} from '../lib/api'
import type {
  AccountInfo,
  AccountLog,
  ActiveRunSummary,
  ScheduledJob,
  KeywordHitRecord,
  AccountStatusJob,
} from '../lib/api'
import type { DashboardLog } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useAuthStore } from '../stores/auth'
import { devLog } from '../lib/devLog'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import { aggregateFailureCategories } from '../lib/run-status'

const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour12: false })
}

export function useDashboardData() {
  const { t } = useI18n()
  const toast = useToast()
  const authStore = useAuthStore()

  let refreshHandle: ChainPollHandle | null = null
  let signHistorySource: EventSource | null = null
  let sseReconnectTimer: ReturnType<typeof setTimeout> | null = null
  let sseReconnectAttempt = 0
  let sseIntentionalClose = false

  const liveConnected = ref(false)
  const pageLoading = ref(true)
  const stats = ref([
    { key: 'dashboard.activeAccounts', value: '...' },
    { key: 'dashboard.totalTasks', value: '...' },
    { key: 'dashboard.recentSuccess', value: '...' },
    { key: 'dashboard.recentFailure', value: '...' },
  ])
  const logs = ref<DashboardLog[]>([])
  const upcomingJobs = ref<ScheduledJob[]>([])
  const activeRuns = ref<ActiveRunSummary[]>([])
  const failureBreakdown = ref<Array<{ category: string; count: number }>>([])
  const recentHits = ref<KeywordHitRecord[]>([])
  const statusJobs = ref<AccountStatusJob[]>([])

  const prependLiveLog = (payload: {
    account_name?: string
    task_name?: string
    success?: boolean
    message?: string
    created_at?: string
    failure_category?: string
  }) => {
    const created = payload.created_at || new Date().toISOString()
    const entry: DashboardLog = {
      time: formatTime(created),
      account: payload.account_name || '-',
      task: payload.task_name || '-',
      status: payload.success ? 'success' : 'error',
      text: (payload.message || '').trim() || payload.task_name || '',
      created_at: created,
      failure_category: payload.failure_category || undefined,
    }
    logs.value = [entry, ...logs.value].slice(0, 40)
    if (payload.success) {
      const s = stats.value.find((x) => x.key === 'dashboard.recentSuccess')
      if (s && s.value !== '...') s.value = String(Number(s.value || 0) + 1)
    } else {
      const s = stats.value.find((x) => x.key === 'dashboard.recentFailure')
      if (s && s.value !== '...') s.value = String(Number(s.value || 0) + 1)
    }
  }

  const clearSseReconnect = () => {
    if (sseReconnectTimer) {
      clearTimeout(sseReconnectTimer)
      sseReconnectTimer = null
    }
  }

  const scheduleSseReconnect = () => {
    if (sseIntentionalClose) return
    clearSseReconnect()
    const delay = Math.min(30_000, 1000 * 2 ** Math.min(sseReconnectAttempt, 5))
    sseReconnectAttempt += 1
    sseReconnectTimer = setTimeout(() => {
      connectSignHistorySSE()
    }, delay)
  }

  const connectSignHistorySSE = () => {
    const token = authStore.token || ''
    if (!token || typeof EventSource === 'undefined') return
    try {
      signHistorySource?.close()
      const url = `/api/events/sign-history?token=${encodeURIComponent(token)}`
      signHistorySource = new EventSource(url)
      signHistorySource.addEventListener('ready', () => {
        liveConnected.value = true
        sseReconnectAttempt = 0
      })
      signHistorySource.addEventListener('sign_log', (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data || '{}')
          prependLiveLog(data)
        } catch (e) {
          devLog.error('parse sign_log event failed', e)
        }
      })
      signHistorySource.onerror = () => {
        liveConnected.value = false
        try {
          signHistorySource?.close()
        } catch {
          /* ignore */
        }
        signHistorySource = null
        scheduleSseReconnect()
      }
    } catch (e) {
      devLog.error('SSE connect failed', e)
      liveConnected.value = false
      scheduleSseReconnect()
    }
  }

  const loadDashboardData = async () => {
    const token = authStore.token || ''
    if (!token) return

    let accRes: { accounts: AccountInfo[]; total: number } = { accounts: [], total: 0 }
    let tasksRes: Awaited<ReturnType<typeof listSignTasks>> = []
    let logsRes: AccountLog[] = []
    let jobsRes: Awaited<ReturnType<typeof listScheduledJobs>> | null = null
    let activeRes: { runs: ActiveRunSummary[] } = { runs: [] }
    let hitsRes: Awaited<ReturnType<typeof listKeywordHits>> | null = null
    let statusJobsRes: Awaited<ReturnType<typeof listAccountStatusCheckJobs>> | null = null

    let loadError: unknown = null
    try { accRes = await listAccounts(token) } catch (e) { loadError = e; devLog.error('Failed to load accounts', e) }
    try { tasksRes = await listSignTasks(token) } catch (e) { loadError = e; devLog.error('Failed to load tasks', e) }
    try { logsRes = await getRecentAccountLogs(token, 50) } catch (e) { loadError = e; devLog.error('Failed to load logs', e) }
    try { jobsRes = await listScheduledJobs(token) } catch (e) { devLog.error('Failed to load scheduled jobs', e) }
    try { activeRes = await listActiveSignTaskRuns(token) } catch (e) { devLog.error('Failed to load active runs', e) }
    try { hitsRes = await listKeywordHits(token, { limit: 8, offset: 0 }) } catch (e) { devLog.error('Failed to load keyword hits', e) }
    try { statusJobsRes = await listAccountStatusCheckJobs(token, 5) } catch (e) { devLog.error('Failed to load status jobs', e) }

    if (loadError && pageLoading.value) {
      toast.error(getLocalizedErrorMessage(loadError, t, t('logs.loadFailed')))
    }

    const activeAccs = accRes.accounts
      ? accRes.accounts.filter((a: AccountInfo) => a.status === 'connected' || a.status === 'checking').length
      : 0

    const today = new Date().toISOString().split('T')[0]
    let todaySuccess = 0
    let todayFail = 0

    if (Array.isArray(logsRes)) {
      logsRes.forEach((l: AccountLog) => {
        if (l.created_at.startsWith(today)) {
          if (l.success) todaySuccess++
          else todayFail++
        }
      })
    }

    stats.value = [
      { key: 'dashboard.activeAccounts', value: `${activeAccs}/${accRes.total || 0}` },
      { key: 'dashboard.totalTasks', value: `${Array.isArray(tasksRes) ? tasksRes.length : 0}` },
      { key: 'dashboard.recentSuccess', value: `${todaySuccess}` },
      { key: 'dashboard.recentFailure', value: `${todayFail}` },
    ]

    if (Array.isArray(logsRes)) {
      logs.value = logsRes.slice(0, 20).map((l: AccountLog) => ({
        time: formatTime(l.created_at),
        account: l.account_name,
        task: l.task_name,
        status: l.success ? 'success' : 'error',
        text: (l.bot_message || l.message || '').trim() || l.task_name,
        created_at: l.created_at,
        failure_category: l.failure_category || undefined,
      }))
    }

    if (jobsRes?.jobs) {
      upcomingJobs.value = jobsRes.jobs
        .filter((j) => j.next_run_time && j.kind !== 'system')
        .slice(0, 8)
    } else {
      upcomingJobs.value = []
    }

    activeRuns.value = Array.isArray(activeRes.runs) ? activeRes.runs : []
    failureBreakdown.value = aggregateFailureCategories(
      Array.isArray(logsRes)
        ? logsRes.map((l) => ({
            success: !!l.success,
            failure_category: l.failure_category,
          }))
        : [],
    )
    recentHits.value = hitsRes?.items || []
    const allStatusJobs = statusJobsRes?.jobs || []
    const activeStatus = allStatusJobs.filter(
      (j) => j.status === 'running' || j.status === 'canceling',
    )
    statusJobs.value = (activeStatus.length ? activeStatus : allStatusJobs).slice(0, 3)
  }

  onMounted(async () => {
    sseIntentionalClose = false
    await loadDashboardData()
    pageLoading.value = false
    refreshHandle = startChainPoll(loadDashboardData, {
      intervalMs: 30000,
      runImmediately: false,
    })
    connectSignHistorySSE()
  })

  onUnmounted(() => {
    sseIntentionalClose = true
    clearSseReconnect()
    refreshHandle?.stop()
    refreshHandle = null
    if (signHistorySource) {
      signHistorySource.close()
      signHistorySource = null
    }
    liveConnected.value = false
  })

  return {
    pageLoading,
    liveConnected,
    stats,
    logs,
    upcomingJobs,
    activeRuns,
    failureBreakdown,
    recentHits,
    statusJobs,
    formatTime,
    loadDashboardData,
  }
}
