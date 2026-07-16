<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { listAccounts, listSignTasks, getRecentAccountLogs, listScheduledJobs } from '../lib/api'
import type { AccountInfo, AccountLog, ScheduledJob } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import type { DashboardLog } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import Modal from '../components/Modal.vue'
import { devLog } from '../lib/devLog'

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
  if (!cat || cat === 'none' || cat === 'unknown') return ''
  const key = `dashboard.failCat.${cat}`
  const label = t(key)
  return label === key ? cat : label
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

    let loadError: unknown = null
    try { accRes = await listAccounts(token) } catch (e) { loadError = e; devLog.error('Failed to load accounts', e) }
    try { tasksRes = await listSignTasks(token) } catch (e) { loadError = e; devLog.error('Failed to load tasks', e) }
    try { logsRes = await getRecentAccountLogs(token, 20) } catch (e) { loadError = e; devLog.error('Failed to load logs', e) }
    try { jobsRes = await listScheduledJobs(token) } catch (e) { devLog.error('Failed to load scheduled jobs', e) }
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
      logs.value = logsRes.map((l: AccountLog) => ({
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
}
</script>

<template>
  <div class="space-y-8">
    <!-- Page Loading -->
    <div v-if="pageLoading" class="flex items-center justify-center py-20">
      <svg class="animate-spin w-6 h-6 text-gray-400" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
    </div>

    <template v-else>
    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div 
        v-for="stat in stats" 
        :key="stat.key"
        class="p-5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 flex flex-col justify-between"
      >
        <span class="text-xs text-gray-500 font-medium tracking-wide">{{ t(stat.key) }}</span>
        <span class="text-2xl font-mono text-gray-900 dark:text-gray-100 mt-2">{{ stat.value }}</span>
      </div>
    </div>

    <!-- Upcoming schedule -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-5">
      <div class="text-xs text-gray-500 font-medium tracking-wide mb-4">{{ t('dashboard.upcomingJobs') }}</div>
      <div v-if="upcomingJobs.length === 0" class="text-xs text-gray-400 py-6 text-center">{{ t('dashboard.noUpcoming') }}</div>
      <div v-else class="space-y-2">
        <div
          v-for="job in upcomingJobs"
          :key="job.id"
          class="flex items-center gap-3 text-xs px-2 py-1.5 hover:bg-gray-50 dark:hover:bg-gray-800/30"
        >
          <span class="font-mono text-gray-500 w-28 shrink-0">{{ formatJobTime(job.next_run_time) }}</span>
          <span class="px-1.5 py-0.5 rounded border text-[10px] shrink-0"
            :class="job.kind === 'sign' ? 'border-sky-200 text-sky-700 dark:border-sky-800 dark:text-sky-300' : 'border-gray-200 text-gray-500'">
            {{ jobKindLabel(job.kind) }}
          </span>
          <span class="truncate text-gray-800 dark:text-gray-200 font-mono" :title="job.id">{{ job.id }}</span>
        </div>
      </div>
    </div>

    <!-- Terminal Logs -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-5 min-h-[400px]">
      <div class="text-xs text-gray-500 font-medium tracking-wide mb-4 flex items-center gap-2">
        <span>{{ t('dashboard.recentLogs') }}</span>
        <span
          class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border"
          :class="liveConnected
            ? 'border-emerald-200 text-emerald-600 dark:border-emerald-800 dark:text-emerald-400'
            : 'border-gray-200 text-gray-400 dark:border-gray-700'"
        >
          <span class="w-1.5 h-1.5 rounded-full" :class="liveConnected ? 'bg-emerald-500' : 'bg-gray-400'" />
          {{ liveConnected ? t('dashboard.liveOn') : t('dashboard.liveOff') }}
        </span>
      </div>
      <div v-if="logs.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
        <p class="text-sm text-gray-500">{{ t('logs.empty') }}</p>
        <p class="text-xs text-gray-400 mt-1">{{ t('logs.emptyHint') }}</p>
      </div>
      <div v-else class="text-xs overflow-x-auto space-y-0">
        <div v-for="(log, idx) in logs" :key="idx"
          class="flex items-center gap-3 hover:bg-gray-50 dark:hover:bg-gray-800/30 px-2 py-2 transition-colors cursor-pointer"
          :title="t('dashboard.openInLogs')"
          @click="selectedLog = log"
          @dblclick="goToLogs(log)"
        >
          <span class="font-mono text-gray-500 dark:text-gray-600 shrink-0 w-[72px] text-[11px]">{{ log.time }}</span>
          <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.account }}</span>
          <span class="text-gray-600 dark:text-gray-500 shrink-0 w-28 truncate">{{ log.task }}</span>
          <span
            class="shrink-0 inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded text-[11px] border"
            :class="log.status === 'success'
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800/50'
              : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800/50'"
          >
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="log.status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'"
            />
            {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
          </span>
          <span
            v-if="log.status === 'error' && failureCategoryLabel(log.failure_category)"
            class="shrink-0 px-1.5 py-0.5 rounded text-[10px] border border-amber-200 text-amber-700 dark:border-amber-800 dark:text-amber-400"
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
            class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs border"
            :class="selectedLog.status === 'success'
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-400 dark:border-emerald-800/50'
              : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/20 dark:text-rose-400 dark:border-rose-800/50'"
          >
            <span
              class="w-1.5 h-1.5 rounded-full"
              :class="selectedLog.status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'"
            />
            {{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}
          </span>
        </div>
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div><span class="text-gray-500">{{ t('logs.time') }}</span><span class="text-gray-900 dark:text-gray-200 font-mono">{{ selectedLog.time }}</span></div>
          <div><span class="text-gray-500">{{ t('logs.account') }}</span><span class="text-gray-900 dark:text-gray-200">{{ selectedLog.account }}</span></div>
          <div class="col-span-2"><span class="text-gray-500">{{ t('logs.task') }}</span><span class="text-gray-900 dark:text-gray-200">{{ selectedLog.task }}</span></div>
          <div v-if="selectedLog.status === 'error' && failureCategoryLabel(selectedLog.failure_category)" class="col-span-2">
            <span class="text-gray-500">{{ t('dashboard.failureCategory') }}</span>
            <span class="text-amber-700 dark:text-amber-400">{{ failureCategoryLabel(selectedLog.failure_category) }}</span>
          </div>
        </div>
        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div class="text-xs text-gray-500 mb-1 font-semibold">{{ t('logs.execInfo') }}</div>
          <div class="p-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs whitespace-pre-wrap break-all max-h-60 overflow-y-auto text-gray-800 dark:text-gray-300">{{ selectedLog.text || t('logs.noDetail') }}</div>
        </div>
        <div class="pt-1 flex justify-end">
          <button
            type="button"
            class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
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
