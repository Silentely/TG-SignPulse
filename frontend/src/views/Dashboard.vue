<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { Users, Zap, Terminal, Settings } from 'lucide-vue-next'
import { listAccounts, listSignTasks, getRecentAccountLogs, listScheduledJobs, listActiveSignTaskRuns } from '../lib/api'
import type { AccountInfo, AccountLog, ActiveRunSummary, ScheduledJob } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import type { DashboardLog } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import Modal from '../components/Modal.vue'
import { devLog } from '../lib/devLog'
import {
  aggregateFailureCategories,
  badgeTone,
  badgeToneClass,
  formatPhaseDetail,
  phaseLabel,
} from '../lib/run-status'

const quickLinks = [
  { name: 'accounts', icon: Users, titleKey: 'dashboard.goAccounts', descKey: 'dashboard.goAccountsDesc' },
  { name: 'tasks', icon: Zap, titleKey: 'dashboard.goTasks', descKey: 'dashboard.goTasksDesc' },
  { name: 'logs', icon: Terminal, titleKey: 'dashboard.goLogs', descKey: 'dashboard.goLogsDesc' },
  { name: 'settings', icon: Settings, titleKey: 'dashboard.goSettings', descKey: 'dashboard.goSettingsDesc' },
]

const { t } = useI18n()
const toast = useToast()
const authStore = useAuthStore()
const router = useRouter()

let refreshTimer: ReturnType<typeof setInterval> | null = null
let signHistorySource: EventSource | null = null
let sseReconnectTimer: ReturnType<typeof setTimeout> | null = null
let sseReconnectAttempt = 0
let sseIntentionalClose = false
const selectedLog = ref<DashboardLog | null>(null)
const liveConnected = ref(false)

/** 跳转到日志页并按账号筛选，附带任务/时间以便自动打开详情 */
const goToLogs = (log: DashboardLog) => {
  router.push({
    name: 'logs',
    query: {
      account: log.account || undefined,
      task: log.task || undefined,
      at: log.created_at || undefined,
    },
  })
}

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
const pageLoading = ref(true)
const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour12: false })
}
const formatJobTime = (iso?: string | null) => {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return iso
  }
}
const jobKindLabel = (kind: string) => {
  if (kind === 'sign') return t('dashboard.jobKindSign')
  if (kind === 'system') return t('dashboard.jobKindSystem')
  if (kind === 'legacy_db') return t('dashboard.jobKindLegacy')
  return kind
}

const failureCategoryLabel = (cat?: string) => {
  if (!cat || cat === 'none') return ''
  const key = `dashboard.failCat.${cat}`
  const label = t(key)
  return label === key ? cat : label
}

const openActiveRun = (run: ActiveRunSummary) => {
  router.push({
    name: 'tasks',
    query: {
      account: run.account_name || undefined,
      task: run.task_name || undefined,
    },
  })
}

const openFailureCategory = (category: string) => {
  if (category === 'session_invalid') {
    router.push({ name: 'accounts' })
    return
  }
  router.push({
    name: 'logs',
    query: { category: category || undefined },
  })
}

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
  // 轻量刷新统计
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
  // 指数退避 1s → 2s → … → 30s，避免代理断流后狂连
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
    // EventSource 无法自定义 Header，仅此路径使用 query token
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
      // 主动关闭后按退避重连；原生 EventSource 自动重连与手动重连二选一，避免双通道
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

onMounted(async () => {
  sseIntentionalClose = false
  await loadDashboardData()
  pageLoading.value = false
  refreshTimer = setInterval(loadDashboardData, 30000)
  connectSignHistorySSE()
})

onUnmounted(() => {
  sseIntentionalClose = true
  clearSseReconnect()
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (signHistorySource) {
    signHistorySource.close()
    signHistorySource = null
  }
  liveConnected.value = false
})

const loadDashboardData = async () => {
  const token = authStore.token || ''
  if (!token) return

    let accRes: { accounts: AccountInfo[]; total: number } = { accounts: [], total: 0 }
    let tasksRes: Awaited<ReturnType<typeof listSignTasks>> = []
    let logsRes: AccountLog[] = []
    let jobsRes: Awaited<ReturnType<typeof listScheduledJobs>> | null = null
    let activeRes: { runs: ActiveRunSummary[] } = { runs: [] }

    let loadError: unknown = null
    try { accRes = await listAccounts(token) } catch (e) { loadError = e; devLog.error('Failed to load accounts', e) }
    try { tasksRes = await listSignTasks(token) } catch (e) { loadError = e; devLog.error('Failed to load tasks', e) }
    try { logsRes = await getRecentAccountLogs(token, 50) } catch (e) { loadError = e; devLog.error('Failed to load logs', e) }
    try { jobsRes = await listScheduledJobs(token) } catch (e) { devLog.error('Failed to load scheduled jobs', e) }
    try { activeRes = await listActiveSignTaskRuns(token) } catch (e) { devLog.error('Failed to load active runs', e) }
    // 仅首屏加载失败时提示，避免 30s 轮询刷屏
    if (loadError && pageLoading.value) {
      toast.error(getLocalizedErrorMessage(loadError, t, t('logs.loadFailed')))
    }

    const activeAccs = accRes.accounts ? accRes.accounts.filter((a: AccountInfo) => a.status === 'connected' || a.status === 'checking').length : 0
    
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
      // 多取用于失败分类聚合；列表展示仍限制 20 条
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
}
</script>

<template>
  <div class="space-y-6">
    <!-- Page Loading skeleton -->
    <div v-if="pageLoading" class="space-y-6" aria-busy="true" aria-live="polite">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div v-for="i in 4" :key="i" class="ui-card p-5 min-h-[96px] space-y-4">
          <div class="ui-skeleton h-3 w-16" />
          <div class="ui-skeleton h-8 w-20" />
        </div>
      </div>
      <div class="ui-card p-5 space-y-3">
        <div class="ui-skeleton h-3 w-28" />
        <div v-for="i in 3" :key="i" class="ui-skeleton h-8 w-full" />
      </div>
      <div class="ui-card p-5 space-y-3 min-h-[240px]">
        <div class="ui-skeleton h-3 w-24" />
        <div v-for="i in 6" :key="i" class="ui-skeleton h-7 w-full" />
      </div>
    </div>

    <template v-else>
    <!-- Stats（可点击跳转） -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
      <button
        v-for="stat in stats"
        :key="stat.key"
        type="button"
        class="ui-card ui-card-hover ui-stat p-5 flex flex-col justify-between min-h-[96px] text-left"
        :style="{
          '--sp-stat-accent':
            stat.key === 'dashboard.activeAccounts' ? '#0ea5e9'
            : stat.key === 'dashboard.totalTasks' ? '#8b5cf6'
            : stat.key === 'dashboard.recentSuccess' ? '#10b981'
            : '#f43f5e'
        }"
        @click="router.push({
          name: stat.key === 'dashboard.totalTasks' ? 'tasks'
            : stat.key === 'dashboard.activeAccounts' ? 'accounts'
            : 'logs'
        })"
      >
        <span class="ui-section-label">{{ t(stat.key) }}</span>
        <span class="text-2xl sm:text-3xl font-mono font-medium text-gray-900 dark:text-gray-100 mt-3 tracking-tight">{{ stat.value }}</span>
      </button>
    </div>

    <!-- 快捷入口 -->
    <div>
      <div class="ui-section-label mb-3">{{ t('dashboard.quickActions') }}</div>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          v-for="link in quickLinks"
          :key="link.name"
          type="button"
          class="ui-card ui-card-hover text-left p-4 group"
          @click="router.push({ name: link.name })"
        >
          <div class="flex items-center gap-2.5 mb-2">
            <span class="ui-section-icon !w-8 !h-8 group-hover:scale-105 transition-transform">
              <component :is="link.icon" class="w-3.5 h-3.5" stroke-width="1.75" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t(link.titleKey) }}</span>
          </div>
          <p class="text-[11px] text-gray-500 leading-relaxed line-clamp-2">{{ t(link.descKey) }}</p>
        </button>
      </div>
    </div>

    <!-- 活跃运行 + 失败分类 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4">{{ t('dashboard.activeRuns') }}</div>
        <div v-if="activeRuns.length === 0" class="text-xs text-gray-400 py-6 text-center">
          {{ t('dashboard.noActiveRuns') }}
        </div>
        <div v-else class="space-y-1">
          <button
            v-for="(run, idx) in activeRuns"
            :key="`${run.task_name}-${run.account_name}-${run.run_id}-${idx}`"
            type="button"
            class="ui-list-row w-full flex items-center gap-2 text-xs px-2 py-2 rounded-sm text-left"
            @click="openActiveRun(run)"
          >
            <span
              class="ui-badge shrink-0 border !text-[10px]"
              :class="badgeToneClass(badgeTone(run))"
            >
              <span class="ui-pulse-dot !bg-sky-500" />
              {{ phaseLabel(run.phase, t) || formatPhaseDetail(run, t) || t('runStatus.inProgress') }}
            </span>
            <span class="font-mono truncate text-gray-800 dark:text-gray-200" :title="run.task_name">{{ run.task_name || '-' }}</span>
            <span class="text-gray-500 truncate shrink-0 max-w-[6rem]" :title="run.account_name">{{ run.account_name || '-' }}</span>
            <span class="ml-auto text-[10px] text-gray-400 font-mono shrink-0 truncate max-w-[40%]" :title="formatPhaseDetail(run, t)">
              {{ formatPhaseDetail(run, t) }}
            </span>
          </button>
        </div>
      </div>
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4">{{ t('dashboard.failureBreakdown') }}</div>
        <div v-if="failureBreakdown.length === 0" class="text-xs text-gray-400 py-6 text-center">
          {{ t('common.noData') }}
        </div>
        <div v-else class="flex flex-wrap gap-2">
          <button
            v-for="item in failureBreakdown"
            :key="item.category"
            type="button"
            class="ui-badge ui-badge-error !text-[11px] cursor-pointer hover:opacity-90"
            @click="openFailureCategory(item.category)"
          >
            {{ failureCategoryLabel(item.category) || item.category }}: {{ item.count }}
          </button>
        </div>
      </div>
    </div>

    <!-- Upcoming schedule -->
    <div class="ui-card p-5">
      <div class="ui-section-label mb-4">{{ t('dashboard.upcomingJobs') }}</div>
      <div v-if="upcomingJobs.length === 0" class="text-xs text-gray-400 py-8 text-center">{{ t('dashboard.noUpcoming') }}</div>
      <div v-else class="space-y-0.5">
        <div
          v-for="job in upcomingJobs"
          :key="job.id"
          class="ui-list-row flex items-center gap-3 text-xs px-2 py-2 rounded-sm"
        >
          <span class="font-mono text-gray-500 w-28 shrink-0">{{ formatJobTime(job.next_run_time) }}</span>
          <span
            class="ui-badge shrink-0"
            :class="job.kind === 'sign' ? 'border-sky-200 text-sky-700 dark:border-sky-800 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/40' : 'ui-badge-neutral'"
          >
            {{ jobKindLabel(job.kind) }}
          </span>
          <span class="truncate text-gray-800 dark:text-gray-200 font-mono" :title="job.id">{{ job.id }}</span>
        </div>
      </div>
    </div>

    <!-- Terminal Logs -->
    <div class="ui-card p-5 min-h-[400px]">
      <div class="ui-section-label mb-4 flex items-center gap-2 flex-wrap">
        <span>{{ t('dashboard.recentLogs') }}</span>
        <span
          class="ui-badge"
          :class="liveConnected ? 'ui-badge-success' : 'ui-badge-neutral'"
        >
          <span :class="liveConnected ? 'ui-pulse-dot' : 'ui-badge-dot'" />
          {{ liveConnected ? t('dashboard.liveOn') : t('dashboard.liveOff') }}
        </span>
      </div>
      <div v-if="logs.length === 0" class="ui-empty py-16">
        <p class="ui-empty-title !text-gray-500 font-normal">{{ t('logs.empty') }}</p>
        <p class="ui-empty-desc">{{ t('logs.emptyHint') }}</p>
      </div>
      <div v-else class="text-xs overflow-x-auto space-y-0">
        <div
          v-for="(log, idx) in logs"
          :key="idx"
          class="ui-list-row flex items-center gap-3 px-2 py-2 cursor-pointer rounded-sm"
          :title="t('dashboard.openInLogs')"
          @click="selectedLog = log"
          @dblclick="goToLogs(log)"
        >
          <span class="font-mono text-gray-500 dark:text-gray-600 shrink-0 w-[72px] text-[11px]">{{ log.time }}</span>
          <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.account }}</span>
          <span class="text-gray-600 dark:text-gray-500 shrink-0 w-28 truncate">{{ log.task }}</span>
          <span
            class="ui-badge shrink-0"
            :class="log.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
          </span>
          <span
            v-if="log.status === 'error' && failureCategoryLabel(log.failure_category)"
            class="ui-badge ui-badge-warn shrink-0"
          >
            {{ failureCategoryLabel(log.failure_category) }}
          </span>
          <span
            class="truncate flex-1 min-w-0"
            :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
            :title="log.text"
          >
            {{ log.text }}
          </span>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <Modal :isOpen="!!selectedLog" @close="selectedLog = null" :title="t('logs.detailTitle')" maxWidthClass="max-w-lg">
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="flex items-center gap-3">
          <span
            class="ui-badge text-xs"
            :class="selectedLog.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}
          </span>
        </div>
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div class="space-y-0.5">
            <div class="text-gray-500">{{ t('logs.time') }}</div>
            <div class="text-gray-900 dark:text-gray-200 font-mono">{{ selectedLog.time }}</div>
          </div>
          <div class="space-y-0.5">
            <div class="text-gray-500">{{ t('logs.account') }}</div>
            <div class="text-gray-900 dark:text-gray-200">{{ selectedLog.account }}</div>
          </div>
          <div class="col-span-2 space-y-0.5">
            <div class="text-gray-500">{{ t('logs.task') }}</div>
            <div class="text-gray-900 dark:text-gray-200">{{ selectedLog.task }}</div>
          </div>
          <div v-if="selectedLog.status === 'error' && failureCategoryLabel(selectedLog.failure_category)" class="col-span-2 space-y-0.5">
            <div class="text-gray-500">{{ t('dashboard.failureCategory') }}</div>
            <div class="text-amber-700 dark:text-amber-400">{{ failureCategoryLabel(selectedLog.failure_category) }}</div>
          </div>
        </div>
        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div class="text-xs text-gray-500 mb-1.5 font-medium">{{ t('logs.execInfo') }}</div>
          <div class="p-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs whitespace-pre-wrap break-all max-h-60 overflow-y-auto text-gray-800 dark:text-gray-300">{{ selectedLog.text || t('logs.noDetail') }}</div>
        </div>
        <div class="pt-1 flex justify-end">
          <button
            type="button"
            class="text-xs text-sky-600 dark:text-sky-400 hover:underline"
            @click="goToLogs(selectedLog); selectedLog = null"
          >
            {{ t('dashboard.openInLogs') }}
          </button>
        </div>
      </div>
    </Modal>
    </template>
  </div>
</template>
