/**
 * 日志页：筛选、加载、详情与清空。
 */
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getTaskHistoryLogs,
  getTaskHistoryLogDetail,
  getLoginAuditLogs,
  clearTaskHistoryLogs,
  clearLoginAuditLogs,
} from '../lib/api'
import { withToken } from '../lib/api/core'
import { useLatestResponseGuard } from '../lib/latest-response'
import { devLog } from '../lib/devLog'
import type { TaskHistoryLog, LoginAuditLog, TaskHistoryLogDetail } from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useAccountsStore } from '../stores/accounts'
import type { TaskLogUiItem, LoginLogUiItem } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import { failureCategoryLabel as mapFailureCategoryLabel } from '../lib/run-status'
import { formatDateTime } from '../lib/datetime'

export function useLogsPage() {
  const { locale, t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const accountsStore = useAccountsStore()
  const route = useRoute()
  const router = useRouter()

  const translateLoginDetail = (detail: string | null | undefined, success: boolean): string => {
    if (!detail) return success ? t('logs.loginSuccess') : t('logs.loginFailed')
    const key = `logs.detail.${detail}`
    const translated = t(key)
    if (translated !== key) return translated
    return detail
  }

  const activeTab = ref<'tasks' | 'login'>('tasks')
  const filterTask = ref('')
  const filterAccount = ref('')
  const filterDate = ref('')
  const filterStatus = ref<'' | 'success' | 'error'>('')
  const filterCategory = ref('')

  const rawTaskLogs = ref<TaskHistoryLog[]>([])
  const pageLoading = ref(true)
  const clearing = ref(false)
  const accountsList = ref<string[]>([])
  const selectedLog = ref<TaskLogUiItem | null>(null)
  const logDetail = ref<TaskHistoryLogDetail | null>(null)
  const detailLoading = ref(false)
  const loginLogs = ref<LoginLogUiItem[]>([])

  // 请求序号守卫：丢弃过期响应，避免慢请求覆盖新筛选/新选中日志
  const taskLogsGuard = useLatestResponseGuard()
  const loginLogsGuard = useLatestResponseGuard()
  const detailGuard = useLatestResponseGuard()

  const accountOptions = computed(() => [
    { label: t('logs.allAccounts'), value: '' },
    ...accountsList.value.map((a) => ({ label: a, value: a })),
  ])

  const statusOptions = computed(() => [
    { label: t('logs.allStatus'), value: '' },
    { label: t('logs.success'), value: 'success' },
    { label: t('logs.failed'), value: 'error' },
  ])

  const categoryOptions = computed(() => [
    { label: t('logs.allCategories'), value: '' },
    { label: t('dashboard.failCat.session_invalid'), value: 'session_invalid' },
    { label: t('dashboard.failCat.flood_wait'), value: 'flood_wait' },
    { label: t('dashboard.failCat.timeout'), value: 'timeout' },
    { label: t('dashboard.failCat.ai_timeout'), value: 'ai_timeout' },
    { label: t('dashboard.failCat.ai_error'), value: 'ai_error' },
    { label: t('dashboard.failCat.button_not_found'), value: 'button_not_found' },
    { label: t('dashboard.failCat.target_not_found'), value: 'target_not_found' },
    { label: t('dashboard.failCat.network_proxy'), value: 'network_proxy' },
    { label: t('dashboard.failCat.strong_failure'), value: 'strong_failure' },
    { label: t('dashboard.failCat.unknown'), value: 'unknown' },
  ])

  const formatTime = (isoString: string) =>
    formatDateTime(isoString, locale.value === 'zh' ? 'zh-CN' : 'en-US', '')

  const failureCategoryLabel = (cat?: string | null) => {
    if (!cat || cat === 'unknown') return ''
    return mapFailureCategoryLabel(cat, t)
  }

  const toTaskUi = (l: TaskHistoryLog): TaskLogUiItem => {
    const preview = (l.bot_message || l.message || '').trim()
    const fallback = l.success
      ? `${t('logs.taskPrefix')}${l.task_name} ${t('logs.success')}`
      : `${t('logs.taskPrefix')}${l.task_name} ${t('logs.failed')}`
    return {
      id: l.id,
      time: formatTime(l.created_at),
      created_at: l.created_at,
      account: l.account_name,
      task: l.task_name,
      status: l.success ? 'success' : 'error',
      text: preview || fallback,
      flow_line_count: l.flow_line_count || 0,
      failure_category: l.failure_category || undefined,
    }
  }

  const logs = computed(() => {
    let filtered = rawTaskLogs.value
    const taskQ = filterTask.value.trim().toLowerCase()
    if (taskQ) {
      filtered = filtered.filter((l) => l.task_name.toLowerCase().includes(taskQ))
    }
    if (filterStatus.value) {
      filtered = filtered.filter((l) =>
        filterStatus.value === 'success' ? l.success : !l.success,
      )
    }
    if (filterCategory.value) {
      filtered = filtered.filter((l) => {
        const raw = String(l.failure_category || "").trim()
        const cat = raw || "unknown"
        return !l.success && cat === filterCategory.value
      })
    }
    return filtered.map(toTaskUi)
  })

  const loadAccounts = async () => {
    return withToken(async () => {
      try {
        // 共享 store 缓存；失败仅记日志，不打断筛选器展示
        const list = await accountsStore.ensureAccounts()
        accountsList.value = list.map((a) => a.name)
      } catch (e: unknown) {
        devLog.error('Failed to load accounts for filter', e)
      }
    })
  }

  const loadTaskLogs = async () => {
    return withToken(async (token) => {
      const seq = taskLogsGuard.next()
      try {
        const res = await getTaskHistoryLogs(token, {
          limit: 100,
          account_name: filterAccount.value || undefined,
          date: filterDate.value || undefined,
        })
        if (!taskLogsGuard.isCurrent(seq)) return // 过期响应：筛选已变化，丢弃
        rawTaskLogs.value = Array.isArray(res) ? res : []
      } catch (e: unknown) {
        if (!taskLogsGuard.isCurrent(seq)) return
        devLog.error('Failed to fetch logs', e)
        notifyApiError(e, 'logs.loadFailed')
        rawTaskLogs.value = []
      }
    })
  }

  const loadLoginLogs = async () => {
    return withToken(async (token) => {
      const seq = loginLogsGuard.next()
      try {
        const res = await getLoginAuditLogs(token, {
          limit: 100,
          date: filterDate.value || undefined,
        })
        if (!loginLogsGuard.isCurrent(seq)) return // 过期响应：筛选已变化，丢弃
        loginLogs.value = res.map((l: LoginAuditLog) => ({
          id: l.id,
          time: formatTime(l.created_at),
          username: l.username,
          ip: l.ip_address || '-',
          status: l.success ? 'success' : 'error',
          text: translateLoginDetail(l.detail, l.success),
        }))
      } catch (e: unknown) {
        if (!loginLogsGuard.isCurrent(seq)) return
        devLog.error('Failed to fetch login logs', e)
        notifyApiError(e, 'logs.loadFailed')
        loginLogs.value = []
      }
    })
  }

  const loadLogs = async () => {
    pageLoading.value = true
    try {
      if (activeTab.value === 'tasks') {
        await loadTaskLogs()
      } else {
        await loadLoginLogs()
      }
    } finally {
      pageLoading.value = false
    }
  }

  const openLogDetail = async (log: TaskLogUiItem) => {
    selectedLog.value = log
    logDetail.value = null
    if (!log.account || !log.task || !log.created_at) return
    return withToken(async (token) => {
      const seq = detailGuard.next()
      detailLoading.value = true
      try {
        const detail = await getTaskHistoryLogDetail(token, {
          account_name: log.account,
          task_name: log.task,
          created_at: log.created_at,
        })
        if (!detailGuard.isCurrent(seq)) return // 过期响应：已选中其他日志，丢弃
        logDetail.value = detail
      } catch (e: unknown) {
        if (!detailGuard.isCurrent(seq)) return
        devLog.error('Failed to fetch log detail', e)
        notifyApiError(e, 'logs.detailLoadFailed')
      } finally {
        if (detailGuard.isCurrent(seq)) detailLoading.value = false
      }
    })
  }

  const handleClear = async () => {
    const isTasks = activeTab.value === 'tasks'
    const confirmMsg = isTasks ? t('logs.clearTasksConfirm') : t('logs.clearLoginConfirm')
    const ok = await confirm({
      title: t('common.dangerConfirm'),
      message: confirmMsg,
      confirmText: t('common.delete'),
      danger: true,
    })
    if (!ok) return

    return withToken(async (token) => {
      clearing.value = true
      try {
        if (isTasks) {
          const res = await clearTaskHistoryLogs(token)
          toast.success(t('logs.clearSuccess', { count: String(res.cleared ?? 0) }))
          rawTaskLogs.value = []
        } else {
          const res = await clearLoginAuditLogs(token)
          toast.success(t('logs.clearSuccess', { count: String(res.cleared ?? 0) }))
          loginLogs.value = []
        }
      } catch (e: unknown) {
        notifyApiError(e, 'logs.clearFailed')
      } finally {
        clearing.value = false
      }
    })
  }

  watch(activeTab, () => {
    loadLogs()
  })

  watch([filterAccount, filterDate], () => {
    loadLogs()
  })

  const tryOpenFromQuery = async () => {
    const taskQ = (route.query.task as string | undefined)?.trim()
    const atQ = (route.query.at as string | undefined)?.trim()
    if (!taskQ || !atQ || activeTab.value !== 'tasks') return

    const match =
      rawTaskLogs.value.find(
        (l) =>
          l.task_name === taskQ &&
          (l.created_at === atQ || l.created_at.startsWith(atQ.slice(0, 19))),
      ) || rawTaskLogs.value.find((l) => l.task_name === taskQ)

    if (match) {
      filterTask.value = taskQ
      await openLogDetail(toTaskUi(match))
    }
  }

  const clearCategoryFilter = () => {
    filterCategory.value = ''
    if (route.query.category) {
      const nextQuery = { ...route.query }
      delete nextQuery.category
      router.replace({ name: 'logs', query: nextQuery })
    }
  }

  const applyRouteQueryFilters = () => {
    const queryAccount =
      typeof route.query.account === 'string' ? route.query.account.trim() : ''
    const queryTask = typeof route.query.task === 'string' ? route.query.task.trim() : ''
    const queryCategory =
      typeof route.query.category === 'string' ? route.query.category.trim() : ''

    if (queryAccount) filterAccount.value = queryAccount
    if (queryTask) filterTask.value = queryTask

    if (queryCategory) {
      filterCategory.value = queryCategory
      filterStatus.value = 'error'
    } else if (filterCategory.value) {
      filterCategory.value = ''
    }
  }

  onMounted(async () => {
    applyRouteQueryFilters()
    loadAccounts()
    await loadLogs()
    await tryOpenFromQuery()
  })

  watch(
    () => [route.query.category, route.query.account, route.query.task] as const,
    () => {
      applyRouteQueryFilters()
    },
  )

  return {
    activeTab,
    filterTask,
    filterAccount,
    filterDate,
    filterStatus,
    filterCategory,
    pageLoading,
    clearing,
    selectedLog,
    logDetail,
    detailLoading,
    loginLogs,
    logs,
    accountOptions,
    statusOptions,
    categoryOptions,
    failureCategoryLabel,
    loadLogs,
    openLogDetail,
    handleClear,
    clearCategoryFilter,
  }
}
