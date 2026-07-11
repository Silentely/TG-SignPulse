<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { listAccounts, listSignTasks, getRecentAccountLogs } from '../lib/api'
import type { AccountInfo, AccountLog } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import type { DashboardLog } from '../lib/types'
import { getErrorMessage } from '../lib/types'
import Modal from '../components/Modal.vue'

const { t } = useI18n()
const toast = useToast()
const authStore = useAuthStore()
const router = useRouter()

let refreshTimer: ReturnType<typeof setInterval> | null = null
const selectedLog = ref<DashboardLog | null>(null)

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
const pageLoading = ref(true)
const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour12: false })
}

onMounted(async () => {
  await loadDashboardData()
  pageLoading.value = false
  refreshTimer = setInterval(loadDashboardData, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

const loadDashboardData = async () => {
  const token = authStore.token || ''
  if (!token) return

    let accRes: { accounts: AccountInfo[]; total: number } = { accounts: [], total: 0 }
    let tasksRes: Awaited<ReturnType<typeof listSignTasks>> = []
    let logsRes: AccountLog[] = []

    let loadError: unknown = null
    try { accRes = await listAccounts(token) } catch (e) { loadError = e; console.error('Failed to load accounts', e) }
    try { tasksRes = await listSignTasks(token) } catch (e) { loadError = e; console.error('Failed to load tasks', e) }
    try { logsRes = await getRecentAccountLogs(token, 20) } catch (e) { loadError = e; console.error('Failed to load logs', e) }
    // 仅首屏加载失败时提示，避免 30s 轮询刷屏
    if (loadError && pageLoading.value) {
      toast.error(getErrorMessage(loadError, t('logs.loadFailed')))
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
      }))
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

    <!-- Terminal Logs -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-5 min-h-[400px]">
      <div class="text-xs text-gray-500 font-medium tracking-wide mb-4">{{ t('dashboard.recentLogs') }}</div>
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
