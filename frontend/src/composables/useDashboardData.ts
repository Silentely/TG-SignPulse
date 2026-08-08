/**
 * 仪表盘：统计/日志/活跃 run 拉取 + 签到历史 SSE。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import {
  listSignTasks,
  getRecentAccountLogs,
  listScheduledJobs,
  listKeywordHits,
  listAccountStatusCheckJobs,
} from '../lib/api'
import type {
  AccountInfo,
  AccountLog,
  ScheduledJob,
  KeywordHitRecord,
  AccountStatusJob,
} from '../lib/api'
import type { DashboardLog } from '../lib/types'
import { getAuthToken } from '../lib/api/core'
import { notifyApiError } from '../lib/notify'
import { useActiveRunsStore } from '../stores/activeRuns'
import { useAccountsStore } from '../stores/accounts'
import { devLog } from '../lib/devLog'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import { aggregateFailureCategories } from '../lib/run-status'
import { formatTimeOnly } from '../lib/datetime'
import { storeToRefs } from 'pinia'

const formatTime = (isoString: string) => formatTimeOnly(isoString)

export function useDashboardData() {
  const activeRunsStore = useActiveRunsStore()
  const accountsStore = useAccountsStore()
  const { runs: activeRuns } = storeToRefs(activeRunsStore)

  let refreshHandle: ChainPollHandle | null = null
  let signHistorySource: EventSource | null = null
  let sseReconnectTimer: ReturnType<typeof setTimeout> | null = null
  let sseReconnectAttempt = 0
  let sseIntentionalClose = false
  // 卸载标记：在途 tick 不再触碰共享 store（避免重启无消费者的轮询）
  let disposed = false

  const liveConnected = ref(false)
  const pageLoading = ref(true)
  const partialLoad = ref(false)
  const stats = ref([
    { key: 'dashboard.activeAccounts', hintKey: 'dashboard.activeAccountsHint', value: '...' },
    { key: 'dashboard.totalTasks', hintKey: 'dashboard.totalTasksHint', value: '...' },
    { key: 'dashboard.recentSuccess', hintKey: 'dashboard.recentSuccessHint', value: '...' },
    { key: 'dashboard.recentFailure', hintKey: 'dashboard.recentFailureHint', value: '...' },
  ])
  const logs = ref<DashboardLog[]>([])
  const upcomingJobs = ref<ScheduledJob[]>([])
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
    const token = getAuthToken()
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
        } catch (e: unknown) {
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
    } catch (e: unknown) {
      devLog.error('SSE connect failed', e)
      liveConnected.value = false
      scheduleSseReconnect()
    }
  }

  const loadDashboardData = async () => {
    const token = getAuthToken()
    if (!token) return

    let accRes: { accounts: AccountInfo[]; total: number } = { accounts: [], total: 0 }
    let tasksRes: Awaited<ReturnType<typeof listSignTasks>> = []
    let logsRes: AccountLog[] = []
    let jobsRes: Awaited<ReturnType<typeof listScheduledJobs>> | null = null
    let hitsRes: Awaited<ReturnType<typeof listKeywordHits>> | null = null
    let statusJobsRes: Awaited<ReturnType<typeof listAccountStatusCheckJobs>> | null = null

    let loadError: unknown = null
    let hasLoadFailure = false
    // 并行拉取相互独立的仪表盘数据，避免串行等待放大首屏延迟；
    // 各请求独立成败，失败仅记录并上报一次，不影响其余数据展示
    const results = await Promise.allSettled([
      accountsStore.ensureAccounts(),
      listSignTasks(token),
      getRecentAccountLogs(token, 50),
      listScheduledJobs(token),
      activeRunsStore.refresh(),
      listKeywordHits(token, { limit: 8, offset: 0 }),
      listAccountStatusCheckJobs(token, 5),
    ])
    const [accResult, tasksResult, logsResult, jobsResult, runsResult, hitsResult, statusJobsResult] = results

    if (accResult.status === 'fulfilled') {
      accRes = { accounts: accountsStore.accounts, total: accountsStore.total }
    } else {
      hasLoadFailure = true
      loadError = accResult.reason
      devLog.error('Failed to load accounts', accResult.reason)
    }
    if (tasksResult.status === 'fulfilled') {
      tasksRes = tasksResult.value
    } else {
      hasLoadFailure = true
      loadError = tasksResult.reason
      devLog.error('Failed to load tasks', tasksResult.reason)
    }
    if (logsResult.status === 'fulfilled') {
      logsRes = logsResult.value
    } else {
      hasLoadFailure = true
      loadError = logsResult.reason
      devLog.error('Failed to load logs', logsResult.reason)
    }
    if (jobsResult.status === 'fulfilled') {
      jobsRes = jobsResult.value
    } else {
      hasLoadFailure = true
      devLog.error('Failed to load scheduled jobs', jobsResult.reason)
    }
    if (runsResult.status === 'rejected') {
      hasLoadFailure = true
      devLog.error('Failed to load active runs', runsResult.reason)
    } else if (runsResult.value === false) {
      hasLoadFailure = true
    }
    if (hitsResult.status === 'fulfilled') {
      hitsRes = hitsResult.value
    } else {
      hasLoadFailure = true
      loadError = hitsResult.reason
      devLog.error('Failed to load keyword hits', hitsResult.reason)
    }
    if (statusJobsResult.status === 'fulfilled') {
      statusJobsRes = statusJobsResult.value
    } else {
      hasLoadFailure = true
      loadError = statusJobsResult.reason
      devLog.error('Failed to load status jobs', statusJobsResult.reason)
    }

    // 卸载后在途 tick：不再写入状态或触发共享轮询
    if (disposed) return

    partialLoad.value = hasLoadFailure

    if (loadError && pageLoading.value) {
      notifyApiError(loadError, 'dashboard.loadFailed')
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
      { key: 'dashboard.activeAccounts', hintKey: 'dashboard.activeAccountsHint', value: `${activeAccs}/${accRes.total || 0}` },
      { key: 'dashboard.totalTasks', hintKey: 'dashboard.totalTasksHint', value: `${Array.isArray(tasksRes) ? tasksRes.length : 0}` },
      { key: 'dashboard.recentSuccess', hintKey: 'dashboard.recentSuccessHint', value: `${todaySuccess}` },
      { key: 'dashboard.recentFailure', hintKey: 'dashboard.recentFailureHint', value: `${todayFail}` },
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

    activeRunsStore.ensurePolling()
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

  // 页面隐藏时暂停 30s 轮询，回到前台立即刷新并恢复：
  // 后台标签页继续高频拉 7 个接口意义有限，徒增资源消耗；SSE 由浏览器节流自行兜底
  const handleVisibilityChange = () => {
    if (disposed) return
    if (document.hidden) {
      refreshHandle?.stop()
      refreshHandle = null
    } else {
      void loadDashboardData()
      if (!refreshHandle?.active) {
        refreshHandle = startChainPoll(loadDashboardData, {
          intervalMs: 30000,
          runImmediately: false,
        })
      }
    }
  }

  onMounted(async () => {
    sseIntentionalClose = false
    activeRunsStore.acquire()
    await loadDashboardData()
    pageLoading.value = false
    refreshHandle = startChainPoll(loadDashboardData, {
      intervalMs: 30000,
      runImmediately: false,
    })
    document.addEventListener('visibilitychange', handleVisibilityChange)
    connectSignHistorySSE()
  })

  onUnmounted(() => {
    disposed = true
    sseIntentionalClose = true
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    clearSseReconnect()
    refreshHandle?.stop()
    refreshHandle = null
    if (signHistorySource) {
      signHistorySource.close()
      signHistorySource = null
    }
    liveConnected.value = false
    activeRunsStore.release()
  })

  return {
    pageLoading,
    partialLoad,
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
