<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, Radio, Clock, Shuffle, Power, Search, Square, X } from 'lucide-vue-next'
import { listSignTasks, deleteSignTask, startSignTaskRun, listAccounts, toggleSignTaskEnabled, batchSignTasks, cloneSignTask, listActiveSignTaskRuns, cancelSignTaskRun, listKeywordHitGroups } from '../lib/api'
import { BUILT_IN_TEMPLATES } from '../lib/task-templates'
import type { SignTask, AccountInfo, ActiveRunSummary } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
import type { TaskUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'
import Modal from '../components/Modal.vue'
import { devLog } from '../lib/devLog'
import {
  badgeTone,
  badgeToneClass,
  formatActiveRunLabel,
  formatPhaseDetail,
  groupActiveRunsByTask,
  isRunInProgress,
  phaseLabel,
  pickPrimaryActiveRun,
  remainingWaitSeconds,
} from '../lib/run-status'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()
const tasks = ref<TaskUiItem[]>([])
const pageLoading = ref(true)
const showAddModal = ref(false)
const addTemplateId = ref<string | null>(null)
/** 账号深链筛选（query.account） */
const accountFilter = computed(() => {
  const q = route.query.account
  return typeof q === 'string' ? q.trim() : ''
})
const showEditModal = ref(false)
const showLogsModal = ref(false)
const editingTask = ref<SignTask | null>(null)
const logsTask = ref<TaskUiItem | null>(null)
const logsRunAccount = ref<string>('')  // Account that just executed the task
const logsInitialTab = ref<'history' | 'hits' | null>(null)

// Account selection for run
const runMenuTask = ref<TaskUiItem | null>(null)
const runMenuAccounts = ref<string[]>([])
const allAccounts = ref<string[]>([])
const selectedTaskIds = ref<Set<string>>(new Set())
const batchBusy = ref(false)
const searchQuery = ref('')
/** 任务模式筛选：全部 / 仅监听 / 仅定时 */
const modeFilter = ref<'all' | 'listen' | 'scheduled'>('all')
const selectedCount = computed(() => selectedTaskIds.value.size)
const cloneBusy = ref(false)
const showCloneModal = ref(false)
const cloneSource = ref<TaskUiItem | null>(null)
const cloneName = ref('')
const showTemplateMenu = ref(false)

const toggleTemplateMenu = (e?: Event) => {
  e?.stopPropagation()
  showTemplateMenu.value = !showTemplateMenu.value
}

const pickTemplate = (templateId: string) => {
  showTemplateMenu.value = false
  handleCreateFromTemplate(templateId)
}
const filteredTasks = computed(() => {
  let list = tasks.value
  if (modeFilter.value === 'listen') {
    list = list.filter((task) => task.isListenMode)
  } else if (modeFilter.value === 'scheduled') {
    list = list.filter((task) => !task.isListenMode)
  }
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return list
  return list.filter(
    (task) =>
      task.name.toLowerCase().includes(q) ||
      task.targetStr.toLowerCase().includes(q) ||
      task.scheduleMode.toLowerCase().includes(q) ||
      task.lastRunStr.toLowerCase().includes(q)
  )
})
const listenTaskCount = computed(() => tasks.value.filter((t) => t.isListenMode).length)
const allSelected = computed(() => filteredTasks.value.length > 0 && filteredTasks.value.every((t) => selectedTaskIds.value.has(t.id)))

const toggleSelectTask = (id: string) => {
  const next = new Set(selectedTaskIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedTaskIds.value = next
}
const toggleSelectAll = () => {
  if (allSelected.value) {
    const next = new Set(selectedTaskIds.value)
    for (const task of filteredTasks.value) next.delete(task.id)
    selectedTaskIds.value = next
  } else {
    const next = new Set(selectedTaskIds.value)
    for (const task of filteredTasks.value) next.add(task.id)
    selectedTaskIds.value = next
  }
}
const clearSelection = () => { selectedTaskIds.value = new Set() }

const runBatch = async (action: 'enable' | 'disable' | 'delete' | 'run') => {
  if (!selectedCount.value || batchBusy.value) return
  if (action === 'delete') {
    const ok = await confirm({
      title: t('common.dangerConfirm'),
      message: `${t('tasks.batchDeleteConfirm')} (${selectedCount.value})`,
      confirmText: t('common.delete'),
      danger: true,
    })
    if (!ok) return
  }
  const token = authStore.token || ''
  const items = tasks.value
    .filter((t) => selectedTaskIds.value.has(t.id))
    .map((t) => ({
      name: t.name,
      account_name: getTaskAccountName(t.raw) || undefined,
    }))
  batchBusy.value = true
  try {
    const res = await batchSignTasks(token, items, action)
    if (res.fail_count === 0) {
      toast.success(`${t('tasks.batchSuccess')}: ${res.success_count}`)
    } else {
      toast.error(`${t('tasks.batchPartial')}: ok=${res.success_count}, fail=${res.fail_count}`)
    }
    clearSelection()
    await loadTasks()
  } catch (e: unknown) {
    toast.error(getLocalizedErrorMessage(e, t, t('tasks.batchFailed')))
  } finally {
    batchBusy.value = false
  }
}

const loadAllAccounts = async () => {
  const token = authStore.token || ''
  if (!token) return
  try {
    const res = await listAccounts(token)
    allAccounts.value = (res.accounts || []).map((a: AccountInfo) => a.name)
  } catch { }
}

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

const getTaskAccountName = (task: SignTask | TaskUiItem): string => {
  // Resolve a usable account name from task data, skipping wildcard '*'
  const raw = 'raw' in task ? task.raw : task
  const name = raw.account_name || ''
  if (name && name !== '*') return name
  const names = raw.account_names || []
  for (const n of names) {
    if (n && n !== '*') return n
  }
  return ''
}

const loadTasks = async () => {
  const token = authStore.token || ''
  if (!token) return

  pageLoading.value = true
  try {
    const accountName = route.query.account as string | undefined
    const res = await listSignTasks(token, accountName)
    tasks.value = res.map((task: SignTask) => {
      const chats = task.chats || []
      const firstChat = chats.length > 0 ? chats[0] : null
      const targetCount = chats.length
      const primaryLabel = firstChat
        ? (firstChat.name || `${firstChat.chat_id}${firstChat.message_thread_id ? '|' + firstChat.message_thread_id : ''}`)
        : t('tasks.noTarget')
      // 列表主标签只显示首个目标；额外数量由 +N badge 展示
      const targetStr = primaryLabel
      
      let scheduleMode = ''
      let modeIcon: typeof Clock | typeof Radio | typeof Shuffle = Clock
      if (task.execution_mode === 'listen') {
        scheduleMode = t('tasks.listenMode')
        modeIcon = Radio
      } else if (task.execution_mode === 'range') {
        scheduleMode = `${task.range_start || '00:00'}-${task.range_end || '23:59'}`
        modeIcon = Shuffle
      } else {
        scheduleMode = task.sign_at || '00:00'
        modeIcon = Clock
      }
                          
      let lastRunStr = t('tasks.notExecuted')
      let lastRunSuccess: boolean | null = null
      // Listen mode tasks run 24H continuously, show "持续运行" instead of "未执行"
      if (task.execution_mode === 'listen' && !task.last_run) {
        lastRunStr = task.enabled !== false ? t('tasks.continuousRunning') : t('tasks.paused')
      }
      if (task.last_run) {
        lastRunSuccess = task.last_run.success
        lastRunStr = `${task.last_run.success ? t('tasks.success') : t('tasks.failed')}-${formatDate(task.last_run.time)}`
      }

      return {
        id: task.name,
        name: task.name,
        scheduleMode,
        targetStr,
        targetCount,
        hitCount: 0,
        lastRunStr,
        lastRunSuccess,
        modeIcon,
        isListenMode: task.execution_mode === 'listen',
        enabled: task.enabled !== false,
        chatAvatarUrl: '',
        chatName: firstChat ? (firstChat.name || `Chat ${firstChat.chat_id}`) : '',
        raw: task
      }
    })

    syncActiveRunsFromTasks(tasks.value)
    ensureActivePolling()
    void loadListenHitCounts()
    if (listenTaskCount.value > 0) ensureHitCountPolling()
    else clearHitCountPolling()

    // Load chat avatars - prefer chat.source_account (the account that selected the chat),
    // fall back to first real account from task's account list
    for (const task of tasks.value) {
      const firstChat = task.raw.chats?.[0]
      if (!firstChat) continue
      const avatarAccount = firstChat.source_account || getTaskAccountName(task.raw)
      if (avatarAccount) {
        loadChatAvatar(task, avatarAccount, firstChat.chat_id)
      }
    }
  } catch (e) {
    devLog.error('Failed to fetch tasks', e)
    toast.error(getLocalizedErrorMessage(e, t, t('tasks.loadFailed')))
    tasks.value = []
  } finally {
    pageLoading.value = false
  }
}

/** 为监听任务填充命中计数角标（失败静默） */
const loadListenHitCounts = async () => {
  const token = authStore.token || ''
  if (!token) return
  const listenTasks = tasks.value.filter((t) => t.isListenMode)
  if (!listenTasks.length) return
  try {
    // 一次按 task 分组拿全量 count，避免 N 次请求
    const res = await listKeywordHitGroups(token, {
      account_name: accountFilter.value || undefined,
      group_by: 'task',
      limit_per_group: 1,
    })
    const countByTask = new Map<string, number>()
    for (const g of res.groups || []) {
      countByTask.set(String(g.key), Number(g.count || 0))
    }
    for (const task of tasks.value) {
      if (!task.isListenMode) continue
      task.hitCount = countByTask.get(task.name) || 0
    }
  } catch (e) {
    devLog.error('Failed to load hit counts', e)
  }
}

let hitCountTimer: ReturnType<typeof setInterval> | null = null
const ensureHitCountPolling = () => {
  if (hitCountTimer) return
  // 有监听任务时定期刷新角标（与日志弹窗自动刷新节奏接近）
  hitCountTimer = setInterval(() => {
    if (listenTaskCount.value > 0) void loadListenHitCounts()
  }, 15000)
}
const clearHitCountPolling = () => {
  if (hitCountTimer) {
    clearInterval(hitCountTimer)
    hitCountTimer = null
  }
}

/** task_name → 该任务下全部活跃 run（多账号） */
const activeRunsByTask = ref<Record<string, ActiveRunSummary[]>>({})
/** 拉取 active-runs 时的本地时间，用于冷却倒计时 */
const activeRunsFetchedAt = ref(0)
const nowTick = ref(Date.now())
let activePollTimer: ReturnType<typeof setInterval> | null = null
let countdownTimer: ReturnType<typeof setInterval> | null = null
const cancelBusyKey = ref('')
const accountStatusMap = ref<Record<string, string>>({})
const accountNeedsRelogin = ref<Record<string, boolean>>({})

const hasAnyActiveRun = computed(() => Object.keys(activeRunsByTask.value).length > 0)

const syncActiveRunsFromTasks = (items: TaskUiItem[]) => {
  const flat: ActiveRunSummary[] = []
  for (const task of items) {
    const ar = task.raw.active_run
    if (ar && isRunInProgress(ar)) {
      flat.push({ ...ar, task_name: ar.task_name || task.name })
    }
  }
  activeRunsByTask.value = groupActiveRunsByTask(flat)
  activeRunsFetchedAt.value = Date.now()
}

const refreshActiveRuns = async () => {
  const token = authStore.token || ''
  if (!token) return
  try {
    const res = await listActiveSignTaskRuns(token)
    activeRunsByTask.value = groupActiveRunsByTask(res.runs || [])
    activeRunsFetchedAt.value = Date.now()
  } catch (e) {
    devLog.error('Failed to refresh active runs', e)
  }
}

const ensureActivePolling = () => {
  if (hasAnyActiveRun.value) {
    if (!activePollTimer) {
      activePollTimer = setInterval(refreshActiveRuns, 4000)
    }
    if (!countdownTimer) {
      countdownTimer = setInterval(() => {
        nowTick.value = Date.now()
      }, 1000)
    }
  } else {
    if (activePollTimer) {
      clearInterval(activePollTimer)
      activePollTimer = null
    }
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }
}

watch(hasAnyActiveRun, () => ensureActivePolling())

const taskActiveRuns = (task: TaskUiItem): ActiveRunSummary[] => {
  return activeRunsByTask.value[task.name] || (task.raw.active_run && isRunInProgress(task.raw.active_run)
    ? [task.raw.active_run]
    : [])
}

const taskActiveRun = (task: TaskUiItem): ActiveRunSummary | null => {
  return pickPrimaryActiveRun(taskActiveRuns(task))
}

const activeRunBadgeText = (task: TaskUiItem): string => {
  const ar = taskActiveRun(task)
  if (!ar || !isRunInProgress(ar)) return ''
  void nowTick.value
  const rem = remainingWaitSeconds(ar.wait_seconds, activeRunsFetchedAt.value, nowTick.value)
  return formatActiveRunLabel(ar, t, { remainingSec: rem })
}

const activeRunTooltip = (task: TaskUiItem): string => {
  const runs = taskActiveRuns(task)
  if (!runs.length) return ''
  return runs
    .map((r) => {
      const acc = r.account_name || '-'
      const ph = phaseLabel(r.phase, t) || formatPhaseDetail(r, t)
      return `${acc}: ${ph}`
    })
    .join('\n')
}

const isAccountInvalid = (accountName: string) => {
  if (accountNeedsRelogin.value[accountName]) return true
  const st = accountStatusMap.value[accountName] || ''
  return st === 'invalid' || st === 'error' || /expired|offline|disconnected/i.test(st)
}

const taskHasInvalidAccount = (task: TaskUiItem): boolean => {
  const names = [
    ...(task.raw.account_names || []),
    task.raw.account_name || '',
  ].filter((n) => n && n !== '*')
  return names.some((n) => isAccountInvalid(n))
}

const handleCancelRun = async (task: TaskUiItem) => {
  const ar = taskActiveRun(task)
  if (!ar?.account_name) {
    toast.error(t('tasks.cancelNeedAccount'))
    return
  }
  const key = `${task.name}:${ar.account_name}`
  if (cancelBusyKey.value === key) return
  cancelBusyKey.value = key
  const token = authStore.token || ''
  try {
    const res = await cancelSignTaskRun(token, task.name, ar.account_name, ar.run_id)
    if (res.ok && res.cancelled) {
      toast.success(t('tasks.cancelSuccess'))
      await refreshActiveRuns()
    } else {
      toast.error(res.error || t('tasks.cancelFailed'))
    }
  } catch (e: unknown) {
    toast.error(getLocalizedErrorMessage(e, t, t('tasks.cancelFailed')))
  } finally {
    cancelBusyKey.value = ''
  }
}

const applyRouteQueryFilters = () => {
  const taskQ = (route.query.task as string | undefined)?.trim()
  if (taskQ) {
    searchQuery.value = taskQ
  }
}

/** 深链 ?tab=hits&task=xxx 时自动打开日志命中 Tab */
const applyLogsDeepLink = () => {
  const tab = String(route.query.tab || '').trim()
  const taskQ = (route.query.task as string | undefined)?.trim()
  if (tab !== 'hits' || !taskQ || !tasks.value.length) return
  const found = tasks.value.find((t) => t.name === taskQ)
  if (!found || !found.isListenMode) return
  // 已对同一任务打开命中 Tab 时不重复打断
  if (
    showLogsModal.value
    && logsTask.value?.name === taskQ
    && logsInitialTab.value === 'hits'
  ) {
    return
  }
  logsRunAccount.value = ''
  logsTask.value = found
  logsInitialTab.value = 'hits'
  showLogsModal.value = true
}

/** 关闭日志弹窗时去掉 tab=hits，避免列表刷新/轮询再次自动弹窗 */
const closeLogsModal = () => {
  showLogsModal.value = false
  logsInitialTab.value = null
  if (String(route.query.tab || '').trim() === 'hits') {
    const nextQuery = { ...route.query }
    delete nextQuery.tab
    router.replace({ name: 'tasks', query: nextQuery })
  }
}

onMounted(async () => {
  applyRouteQueryFilters()
  await loadTasks()
  applyLogsDeepLink()
  loadAllAccounts()
  try {
    const token = authStore.token || ''
    if (token) {
      const res = await listAccounts(token)
      const map: Record<string, string> = {}
      const relogin: Record<string, boolean> = {}
      for (const a of res.accounts || []) {
        map[a.name] = String(a.status || '')
        relogin[a.name] = !!a.needs_relogin
      }
      accountStatusMap.value = map
      accountNeedsRelogin.value = relogin
    }
  } catch (e) {
    devLog.error('Failed to load account status map', e)
  }
})

watch(() => route.query.task, () => applyRouteQueryFilters())
watch(
  () => [route.query.tab, route.query.task, tasks.value.length] as const,
  () => applyLogsDeepLink(),
)

onUnmounted(() => {
  if (activePollTimer) {
    clearInterval(activePollTimer)
    activePollTimer = null
  }
  if (countdownTimer) {
    clearInterval(countdownTimer)
    countdownTimer = null
  }
  clearHitCountPolling()
})

const loadChatAvatar = async (task: TaskUiItem, accountName: string, chatId: number) => {
  const token = authStore.token || ''
  // Use chat_id as cache key - avatar is the same regardless of which account fetched it
  const cacheKey = `chat_avatar_${chatId}`
  const noAvatarKey = `chat_avatar_${chatId}_404`
  
  // Check localStorage cache first (persists across browser sessions)
  const cached = localStorage.getItem(cacheKey)
  if (cached && cached !== '__no_avatar__') {
    task.chatAvatarUrl = cached
    return
  }

  // Check if we recently confirmed no avatar (within 1 hour) to avoid spam
  const noAvatarTime = localStorage.getItem(noAvatarKey)
  if (noAvatarTime) {
    const age = Date.now() - parseInt(noAvatarTime, 10)
    if (age < 3600000) {  // 1 hour
      return
    }
  }

  try {
    const res = await fetch(`/api/sign-tasks/chats/${encodeURIComponent(accountName)}/avatar/${chatId}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (res.ok) {
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      task.chatAvatarUrl = url
      // Clear no-avatar marker
      localStorage.removeItem(noAvatarKey)
      // Cache as data URL for persistence
      try {
        const reader = new FileReader()
        reader.onload = () => {
          if (reader.result) {
            try {
              localStorage.setItem(cacheKey, reader.result as string)
            } catch {
              // localStorage quota exceeded - fall back to sessionStorage
              try { sessionStorage.setItem(cacheKey, reader.result as string) } catch {}
            }
          }
        }
        reader.readAsDataURL(blob)
      } catch {}
    } else if (res.status === 404) {
      // Mark with timestamp to retry after 1 hour
      try { localStorage.setItem(noAvatarKey, String(Date.now())) } catch {}
    }
  } catch {
    // Network error, don't cache
  }
}

watch(() => route.query.account, () => {
  loadTasks()
})

const openCloneModal = (task: TaskUiItem) => {
  cloneSource.value = task
  cloneName.value = `${task.name}_copy`
  showCloneModal.value = true
}

const closeCloneModal = () => {
  showCloneModal.value = false
  cloneSource.value = null
  cloneName.value = ''
}

const submitClone = async () => {
  if (cloneBusy.value || !cloneSource.value) return
  const newName = cloneName.value.trim()
  if (!newName) {
    toast.error(t('tasks.cloneNameRequired'))
    return
  }
  if (/[/\\]/.test(newName)) {
    toast.error(t('tasks.cloneNameInvalid'))
    return
  }
  const token = authStore.token || ''
  cloneBusy.value = true
  try {
    await cloneSignTask(
      token,
      cloneSource.value.name,
      newName,
      cloneSource.value.raw.account_name || undefined,
    )
    toast.success(t('tasks.cloneSuccess'))
    closeCloneModal()
    await loadTasks()
  } catch (e) {
    toast.error(getLocalizedErrorMessage(e, t, t('tasks.cloneFailed')))
  } finally {
    cloneBusy.value = false
  }
}

const openAddBlank = () => {
  addTemplateId.value = null
  showAddModal.value = true
}

const closeAddModal = () => {
  showAddModal.value = false
  addTemplateId.value = null
}

const clearAccountFilter = () => {
  const nextQuery = { ...route.query }
  delete nextQuery.account
  router.push({ name: 'tasks', query: nextQuery })
}

const preferAccountForCreate = computed(() => {
  if (accountFilter.value) return accountFilter.value
  return allAccounts.value[0] || null
})

const handleCreateFromTemplate = (templateId: string) => {
  // 预填动作到新建表单；chat_id 仍由用户选择，避免落库无效任务
  if (!allAccounts.value.length) {
    toast.error(t('tasks.templateNeedAccount'))
    return
  }
  addTemplateId.value = templateId
  showAddModal.value = true
}

const handleDelete = async (task: TaskUiItem) => {
  const ok = await confirm({
    title: t('common.dangerConfirm'),
    message: `${t('tasks.deleteConfirm')} ${task.name} ?`,
    confirmText: t('common.delete'),
    danger: true,
  })
  if (!ok) return
  const token = authStore.token || ''
  try {
    const accountName = getTaskAccountName(task.raw) || undefined
    await deleteSignTask(token, task.name, accountName)
    toast.success(t('tasks.deleteSuccess'))
    await loadTasks()
  } catch (e: unknown) {
    toast.error(`${t('tasks.deleteFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`)
  }
}

const handleToggleEnabled = async (task: TaskUiItem) => {
  const token = authStore.token || ''
  try {
    const accountName = getTaskAccountName(task.raw) || undefined
    await toggleSignTaskEnabled(token, task.name, accountName)
    toast.success(task.enabled ? t('tasks.pauseSuccess') : t('tasks.resumeSuccess'))
    await loadTasks()
  } catch (e: unknown) {
    toast.error(`${t('tasks.toggleFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`)
  }
}

const getTaskRealAccounts = (task: TaskUiItem | SignTask): string[] => {
  const raw = 'raw' in task ? task.raw : task
  const names = raw.account_names || []
  if (names.includes('*')) {
    // Wildcard: expand to all accounts
    return allAccounts.value.length > 0 ? allAccounts.value : []
  }
  return names.filter((n: string) => n && n !== '*')
}

const handleRun = (task: TaskUiItem) => {
  const accounts = getTaskRealAccounts(task)
  if (accounts.length <= 1) {
    // Single account or no accounts - run directly
    doRun(task, accounts[0] || getTaskAccountName(task.raw))
  } else {
    // Multiple accounts - show selection menu
    runMenuTask.value = task
    runMenuAccounts.value = accounts
  }
}

const doRun = async (task: TaskUiItem, accountName: string) => {
  runMenuTask.value = null
  const token = authStore.token || ''
  try {
    await startSignTaskRun(token, task.name, accountName)
    // Open logs modal with the specific account that was just run
    logsRunAccount.value = accountName
    logsTask.value = task
    showLogsModal.value = true
  } catch (e: unknown) {
    toast.error(`${t('tasks.triggerFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`)
  }
}

const closeRunMenu = () => {
  runMenuTask.value = null
  showTemplateMenu.value = false
}

const openEdit = (task: TaskUiItem) => {
  editingTask.value = task.raw
  showEditModal.value = true
}

const openLogs = (task: TaskUiItem, tab: 'history' | 'hits' | null = null) => {
  logsRunAccount.value = ''  // No specific run account, show aggregated history
  logsTask.value = task
  logsInitialTab.value = tab
  showLogsModal.value = true
}
</script>

<template>
  <div class="relative min-h-[80vh]" @click="closeRunMenu">
    <!-- Page Loading skeleton -->
    <div v-if="pageLoading" class="space-y-2" aria-busy="true">
      <div class="ui-card p-3">
        <div class="ui-skeleton h-6 w-full max-w-md" />
      </div>
      <div v-for="i in 5" :key="i" class="ui-card p-4 flex items-center gap-3">
        <div class="ui-skeleton w-10 h-10 shrink-0" />
        <div class="flex-1 space-y-2">
          <div class="ui-skeleton h-3.5 w-40" />
          <div class="ui-skeleton h-3 w-64 max-w-full" />
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-else-if="tasks.length === 0" class="space-y-3">
      <div
        v-if="accountFilter"
        class="ui-card flex flex-wrap items-center justify-between gap-2 px-3 py-2 border border-sky-200/70 dark:border-sky-800/50 bg-sky-50/80 dark:bg-sky-950/30"
      >
        <div class="text-xs text-sky-800 dark:text-sky-200 min-w-0">
          <span class="text-sky-600/80 dark:text-sky-400/80">{{ t('tasks.accountFilter') }}：</span>
          <span class="font-mono font-medium truncate">{{ accountFilter }}</span>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1 text-[11px] text-sky-700 dark:text-sky-300 hover:underline shrink-0"
          @click="clearAccountFilter"
        >
          <X class="w-3 h-3" />
          {{ t('tasks.clearAccountFilter') }}
        </button>
      </div>
      <div class="ui-empty">
        <div class="ui-empty-icon">
          <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <p class="ui-empty-title">{{ t('tasks.empty') }}</p>
        <p class="ui-empty-desc mb-4">{{ t('tasks.emptyHint') }}</p>
        <div class="flex flex-wrap items-center justify-center gap-2">
          <div class="relative" @click.stop>
            <button type="button" class="ui-btn-secondary !text-xs !px-3 !py-2" @click="toggleTemplateMenu">
              {{ t('tasks.fromTemplate') }}
            </button>
            <div
              v-if="showTemplateMenu"
              class="absolute left-1/2 -translate-x-1/2 top-full mt-1 z-20 min-w-[14rem] max-h-64 overflow-y-auto ui-dropdown shadow-[var(--sp-shadow-md)] p-1"
            >
              <button
                v-for="tpl in BUILT_IN_TEMPLATES"
                :key="tpl.id"
                type="button"
                class="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm"
                @click="pickTemplate(tpl.id)"
              >
                <div class="font-medium">{{ t(tpl.nameKey) }}</div>
                <div class="text-[10px] text-gray-500">{{ t(tpl.descKey) }}</div>
              </button>
            </div>
          </div>
          <button type="button" class="ui-btn-primary !text-xs !px-3 !py-2" @click="openAddBlank">
            <Plus class="w-3.5 h-3.5" /> {{ t('taskModal.addTitle') }}
          </button>
        </div>
      </div>
    </div>

    <div v-else class="flex flex-col gap-3 pb-24">
    <!-- 账号深链筛选条 -->
    <div
      v-if="accountFilter"
      class="ui-card flex flex-wrap items-center justify-between gap-2 px-3 py-2 border border-sky-200/70 dark:border-sky-800/50 bg-sky-50/80 dark:bg-sky-950/30"
    >
      <div class="text-xs text-sky-800 dark:text-sky-200 min-w-0">
        <span class="text-sky-600/80 dark:text-sky-400/80">{{ t('tasks.accountFilter') }}：</span>
        <span class="font-mono font-medium truncate">{{ accountFilter }}</span>
      </div>
      <button
        type="button"
        class="inline-flex items-center gap-1 text-[11px] text-sky-700 dark:text-sky-300 hover:underline shrink-0"
        @click="clearAccountFilter"
      >
        <X class="w-3 h-3" />
        {{ t('tasks.clearAccountFilter') }}
      </button>
    </div>
    <!-- 工具栏：不使用 sticky，避免与列表层叠重叠 -->
    <div
      class="ui-card p-3 space-y-2.5"
      :class="selectedCount ? 'ring-1 ring-sky-400/30 border-sky-300/40 dark:border-sky-700/40' : ''"
      role="toolbar"
      :aria-label="t('tasks.selectAll')"
    >
      <div class="flex flex-col sm:flex-row sm:items-center gap-2">
        <label
          class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer select-none shrink-0"
          :title="searchQuery.trim() ? t('tasks.selectAllFilteredHint') : undefined"
        >
          <input
            type="checkbox"
            :checked="allSelected"
            class="ui-checkbox"
            :aria-checked="allSelected"
            @change="toggleSelectAll"
          />
          {{ searchQuery.trim() ? t('tasks.selectAllFiltered') : t('tasks.selectAll') }}
        </label>
        <div class="relative flex-1 min-w-0">
          <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            v-model="searchQuery"
            type="search"
            class="ui-input !pl-8 !h-9 !text-xs"
            :placeholder="t('common.searchPlaceholder')"
            :aria-label="t('common.search')"
          >
        </div>
        <div class="flex items-center gap-1 shrink-0 text-[11px]">
          <button
            type="button"
            class="px-2 py-1 rounded-sm border transition-colors"
            :class="modeFilter === 'all'
              ? 'border-sky-400 text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/30'
              : 'border-gray-200 dark:border-gray-700 text-gray-500'"
            @click="modeFilter = 'all'"
          >
            {{ t('tasks.filterAll') }}
          </button>
          <button
            type="button"
            class="px-2 py-1 rounded-sm border transition-colors"
            :class="modeFilter === 'listen'
              ? 'border-orange-400 text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-950/30'
              : 'border-gray-200 dark:border-gray-700 text-gray-500'"
            @click="modeFilter = 'listen'"
          >
            {{ t('tasks.filterListen') }}
            <span v-if="listenTaskCount" class="font-mono opacity-80">({{ listenTaskCount }})</span>
          </button>
          <button
            type="button"
            class="px-2 py-1 rounded-sm border transition-colors"
            :class="modeFilter === 'scheduled'
              ? 'border-violet-400 text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-950/30'
              : 'border-gray-200 dark:border-gray-700 text-gray-500'"
            @click="modeFilter = 'scheduled'"
          >
            {{ t('tasks.filterScheduled') }}
          </button>
        </div>
        <div v-if="selectedCount" class="flex items-center gap-2 shrink-0">
          <span class="text-xs font-mono text-sky-700 dark:text-sky-300">
            {{ t('tasks.selectedCount') }}: {{ selectedCount }}
          </span>
          <button
            type="button"
            class="text-[11px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 underline-offset-2 hover:underline"
            @click="clearSelection"
          >
            {{ t('common.cancel') }}
          </button>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs" :disabled="!selectedCount || batchBusy" @click="runBatch('enable')">{{ t('tasks.batchEnable') }}</button>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs" :disabled="!selectedCount || batchBusy" @click="runBatch('disable')">{{ t('tasks.batchDisable') }}</button>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs" :disabled="!selectedCount || batchBusy" @click="runBatch('run')">{{ t('tasks.batchRun') }}</button>
        <button type="button" class="ui-btn-danger !px-2.5 !py-1.5 !text-xs" :disabled="!selectedCount || batchBusy" @click="runBatch('delete')">{{ t('tasks.batchDelete') }}</button>
        <div class="relative ml-auto" @click.stop>
          <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs" @click="toggleTemplateMenu">
            {{ t('tasks.fromTemplate') }}
          </button>
          <div
            v-if="showTemplateMenu"
            class="absolute right-0 top-full mt-1 z-30 min-w-[14rem] max-h-64 overflow-y-auto ui-dropdown shadow-[var(--sp-shadow-md)] p-1"
          >
            <button
              v-for="tpl in BUILT_IN_TEMPLATES"
              :key="tpl.id"
              type="button"
              class="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm"
              @click="pickTemplate(tpl.id)"
            >
              <div class="font-medium">{{ t(tpl.nameKey) }}</div>
              <div class="text-[10px] text-gray-500">{{ t(tpl.descKey) }}</div>
            </button>
          </div>
        </div>
        <button type="button" class="ui-btn-primary !px-2.5 !py-1.5 !text-xs" @click="openAddBlank">
          <Plus class="w-3.5 h-3.5" /> {{ t('taskModal.addTitle') }}
        </button>
        <span v-if="batchBusy" class="ui-spinner !w-3.5 !h-3.5 !border-2" aria-hidden="true" />
      </div>
    </div>

    <div v-if="filteredTasks.length === 0" class="ui-empty !py-12">
      <p class="ui-empty-desc">{{ t('common.noData') }}</p>
    </div>

    <div
      v-for="task in filteredTasks"
      :key="task.id"
      class="ui-card relative flex flex-col gap-3 p-4"
      :class="{
        'opacity-55': !task.enabled,
        'ring-1 ring-sky-400/40 border-sky-300/50 dark:border-sky-700/40': selectedTaskIds.has(task.id),
      }"
    >
      <!-- 主信息行 -->
      <div class="flex items-start gap-3 min-w-0">
        <label class="pt-1 shrink-0 cursor-pointer" @click.stop>
          <input
            type="checkbox"
            :checked="selectedTaskIds.has(task.id)"
            class="ui-checkbox"
            @change="toggleSelectTask(task.id)"
          />
        </label>
        <div class="w-10 h-10 shrink-0 bg-gray-100 dark:bg-gray-800/80 flex items-center justify-center text-gray-500 border border-gray-200 dark:border-gray-700/60 overflow-hidden">
          <img v-if="task.chatAvatarUrl" :src="task.chatAvatarUrl" class="w-full h-full object-cover" alt="" />
          <component v-else :is="task.modeIcon" class="w-5 h-5 opacity-70" />
        </div>
        <div class="flex-1 min-w-0 space-y-1.5">
          <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate" :title="task.name">
            {{ task.name }}
          </div>
          <div class="flex flex-wrap items-center gap-1.5">
            <span
              class="ui-badge !text-[11px] font-mono bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50 max-w-[12rem] truncate"
              :title="task.scheduleMode"
            >
              {{ task.scheduleMode }}
            </span>
            <span
              class="ui-badge ui-badge-neutral !text-[11px] font-mono max-w-[16rem] truncate"
              :title="task.targetStr"
            >
              {{ task.targetStr }}
            </span>
            <span
              v-if="task.targetCount > 1"
              class="ui-badge !text-[11px] bg-violet-50 text-violet-700 border-violet-100 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-800/50"
              :title="task.targetStr"
            >
              {{ t('tasks.extraTargets', { n: task.targetCount - 1 }) }}
            </span>
            <button
              v-if="task.isListenMode && (task.hitCount || 0) > 0"
              type="button"
              class="ui-badge !text-[11px] bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50 cursor-pointer hover:opacity-90"
              :title="t('tasks.hitsBadgeHint')"
              @click.stop="openLogs(task, 'hits')"
            >
              {{ t('tasks.hitsBadge', { n: task.hitCount }) }}
            </button>
            <span
              class="ui-badge !text-[11px] max-w-full truncate"
              :title="task.lastRunStr"
              :class="task.isListenMode && task.lastRunSuccess === null
                ? 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800/50'
                : task.lastRunSuccess === null
                  ? 'ui-badge-neutral'
                  : (task.lastRunSuccess ? 'ui-badge-success' : 'ui-badge-error')"
            >
              {{ task.lastRunStr }}
            </span>
            <span
              v-if="taskActiveRun(task) && isRunInProgress(taskActiveRun(task))"
              class="ui-badge !text-[11px] max-w-[16rem] truncate border"
              :class="badgeToneClass(badgeTone(taskActiveRun(task)))"
              :title="activeRunTooltip(task) || activeRunBadgeText(task)"
            >
              <span class="ui-pulse-dot !bg-sky-500 mr-1" />
              {{ activeRunBadgeText(task) }}
              <template v-if="taskActiveRuns(task).length > 1">
                ·{{ taskActiveRuns(task).length }}
              </template>
            </span>
            <span
              v-if="taskHasInvalidAccount(task)"
              class="ui-badge ui-badge-error !text-[11px]"
              :title="t('tasks.accountInvalidHint')"
            >
              {{ t('tasks.accountInvalid') }}
            </span>
          </div>
        </div>
      </div>

      <!-- 操作行：单独一行，避免与内容挤在一起 -->
      <div class="flex flex-wrap items-center gap-1 border-t border-gray-100 dark:border-gray-800/50 pt-2.5">
        <button
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 rounded-sm text-xs transition-colors"
          :class="task.enabled
            ? 'text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20'
            : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-white/[0.04]'"
          :title="task.enabled ? t('tasks.pause') : t('tasks.resume')"
          :aria-pressed="task.enabled"
          @click="handleToggleEnabled(task)"
        >
          <Power class="w-3.5 h-3.5" />
          <span>{{ task.enabled ? t('tasks.pause') : t('tasks.resume') }}</span>
        </button>
        <button
          v-if="taskActiveRun(task) && isRunInProgress(taskActiveRun(task))"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 rounded-sm text-xs text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/20 transition-colors"
          :title="t('tasks.cancelRun')"
          :disabled="cancelBusyKey === `${task.name}:${taskActiveRun(task)?.account_name || ''}`"
          @click="handleCancelRun(task)"
        >
          <Square class="w-3.5 h-3.5" />
          <span>{{ t('tasks.cancelRun') }}</span>
        </button>
        <div class="relative" @click.stop>
          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-1.5 rounded-sm text-xs transition-colors"
            :class="task.raw.execution_mode === 'listen' || taskHasInvalidAccount(task)
              ? 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
              : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04]'"
            :title="taskHasInvalidAccount(task) ? t('tasks.accountInvalidHint') : t('tasks.executeNow')"
            :disabled="task.raw.execution_mode === 'listen' || taskHasInvalidAccount(task)"
            @click="task.raw.execution_mode !== 'listen' && !taskHasInvalidAccount(task) && handleRun(task)"
          >
            <Play class="w-3.5 h-3.5" />
            <span>{{ t('tasks.execute') }}</span>
          </button>
          <div
            v-if="runMenuTask === task"
            class="absolute top-full left-0 mt-1 z-50 min-w-[140px] ui-card shadow-[var(--sp-shadow-md)] py-1"
          >
            <div class="px-3 py-1.5 text-[10px] text-gray-400 font-medium uppercase tracking-wide border-b border-gray-100 dark:border-gray-800">
              {{ t('tasks.selectAccount') }}
            </div>
            <button
              v-for="acc in runMenuAccounts"
              :key="acc"
              type="button"
              class="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] transition-colors truncate"
              @click="doRun(task, acc)"
            >
              {{ acc }}
            </button>
          </div>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] rounded-sm transition-colors text-xs"
          :title="t('tasks.viewLogs')"
          @click="openLogs(task)"
        >
          <FileText class="w-3.5 h-3.5" />
          <span>{{ t('tasks.logs') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] rounded-sm transition-colors text-xs"
          :title="t('tasks.clone')"
          :disabled="cloneBusy"
          @click="openCloneModal(task)"
        >
          <span>{{ t('tasks.clone') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] rounded-sm transition-colors text-xs"
          :title="t('tasks.edit')"
          @click="openEdit(task)"
        >
          <Edit2 class="w-3.5 h-3.5" />
          <span>{{ t('tasks.edit') }}</span>
        </button>
        <button
          type="button"
          class="inline-flex items-center gap-1 px-2 py-1.5 text-gray-600 dark:text-gray-300 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-sm transition-colors text-xs"
          :title="t('tasks.delete')"
          @click="handleDelete(task)"
        >
          <Trash2 class="w-3.5 h-3.5" />
          <span>{{ t('tasks.delete') }}</span>
        </button>
      </div>
    </div>
    </div>
    
    <div class="fixed ui-safe-fab z-40 flex flex-col items-end gap-2">
      <button 
        type="button"
        class="ui-fab"
        :aria-label="t('taskModal.addTitle')"
        :title="t('taskModal.addTitle')"
        @click="openAddBlank"
      >
        <Plus class="w-5 h-5" />
      </button>
    </div>

    <!-- Modals -->
    <AddTaskModal
      :isOpen="showAddModal"
      :template-id="addTemplateId"
      :prefer-account="preferAccountForCreate"
      @close="closeAddModal"
      @success="loadTasks"
    />
    <EditTaskModal v-if="editingTask" :isOpen="showEditModal" :task="editingTask" @close="showEditModal = false" @success="loadTasks" />
    <TaskLogsModal
      :isOpen="showLogsModal"
      :task="logsTask"
      :runAccount="logsRunAccount"
      :initial-tab="logsInitialTab"
      @close="closeLogsModal"
    />

    <Modal :isOpen="showCloneModal" :title="t('tasks.cloneTitle')" maxWidthClass="max-w-sm" @close="closeCloneModal">
      <div class="space-y-3">
        <p class="text-xs text-gray-500">
          {{ t('tasks.cloneFrom', { name: cloneSource?.name || '' }) }}
        </p>
        <div class="space-y-1.5">
          <label class="ui-label" for="clone-task-name">{{ t('tasks.cloneName') }}</label>
          <input
            id="clone-task-name"
            v-model="cloneName"
            type="text"
            class="ui-input"
            autocomplete="off"
            @keyup.enter="submitClone"
          >
        </div>
      </div>
      <template #footer>
        <button type="button" class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2" @click="closeCloneModal">
          {{ t('common.cancel') }}
        </button>
        <button type="button" class="ui-btn-primary !px-4 !py-2" :disabled="cloneBusy" @click="submitClone">
          {{ cloneBusy ? t('tasks.cloning') : t('tasks.clone') }}
        </button>
      </template>
    </Modal>
  </div>
</template>
