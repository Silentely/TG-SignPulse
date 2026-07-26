/**
 * 日志页：筛选、加载、详情与清空。
 */
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getTaskHistoryLogs,
  getTaskHistoryLogDetail,
  getLoginAuditLogs,
  listAccounts,
  clearTaskHistoryLogs,
  clearLoginAuditLogs,
} from '../lib/api'
import { devLog } from '../lib/devLog'
import type { TaskHistoryLog, LoginAuditLog, TaskHistoryLogDetail, AccountInfo } from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useAuthStore } from '../stores/auth'
import type { TaskLogUiItem, LoginLogUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import { failureCategoryLabel as mapFailureCategoryLabel } from '../lib/run-status'

export function useLogsPage() {
  const { locale, t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const authStore = useAuthStore()
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

  const formatTime = (isoString: string) => {
    if (!isoString) return ''
    const d = new Date(isoString)
    const loc = locale.value === 'zh' ? 'zh-CN' : 'en-US'
    return d.toLocaleString(loc, { hour12: false })
  }

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
        const cat = String(l.failure_category || 'unknown')
        return !l.success && cat === filterCategory.value
      })
    }
    return filtered.map(toTaskUi)
  })

  const loadAccounts = async () => {
    const token = authStore.token || ''
    if (!token) return
    try {
      const res = await listAccounts(token)
      accountsList.value = res.accounts.map((a: AccountInfo) => a.name)
    } catch (e) {
      devLog.error('Failed to load accounts for filter', e)
    }
  }

  const loadTaskLogs = async () => {
    const token = authStore.token || ''
    if (!token) return
    try {
      const res = await getTaskHistoryLogs(token, {
        limit: 100,
        account_name: filterAccount.value || undefined,
        date: filterDate.value || undefined,
      })
      rawTaskLogs.value = Array.isArray(res) ? res : []
    } catch (e) {
      devLog.error('Failed to fetch logs', e)
      toast.error(getLocalizedErrorMessage(e, t, t('logs.loadFailed')))
      rawTaskLogs.value = []
    }
  }

  const loadLoginLogs = async () => {
    const token = authStore.token || ''
    if (!token) return
    try {
      const res = await getLoginAuditLogs(token, {
        limit: 100,
        date: filterDate.value || undefined,
      })
      loginLogs.value = res.map((l: LoginAuditLog) => ({
        id: l.id,
        time: formatTime(l.created_at),
        username: l.username,
        ip: l.ip_address || '-',
        status: l.success ? 'success' : 'error',
        text: translateLoginDetail(l.detail, l.success),
      }))
    } catch (e) {
      devLog.error('Failed to fetch login logs', e)
      toast.error(getLocalizedErrorMessage(e, t, t('logs.loadFailed')))
      loginLogs.value = []
    }
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
    const token = authStore.token || ''
    if (!token || !log.account || !log.task || !log.created_at) return
    detailLoading.value = true
    try {
      const detail = await getTaskHistoryLogDetail(token, {
        account_name: log.account,
        task_name: log.task,
        created_at: log.created_at,
      })
      logDetail.value = detail
    } catch (e) {
      devLog.error('Failed to fetch log detail', e)
      toast.error(getLocalizedErrorMessage(e, t, t('logs.detailLoadFailed')))
    } finally {
      detailLoading.value = false
    }
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

    const token = authStore.token || ''
    if (!token) return

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
    } catch (e) {
      toast.error(getLocalizedErrorMessage(e, t, t('logs.clearFailed')))
    } finally {
      clearing.value = false
    }
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
