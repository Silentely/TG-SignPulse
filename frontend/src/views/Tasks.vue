<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Radio, Clock, Shuffle, Power, Search, X, LayoutTemplate, Pause, Play, Trash2 } from 'lucide-vue-next'
import { listSignTasks, deleteSignTask, startSignTaskRun, listAccounts, toggleSignTaskEnabled, batchSignTasks, cloneSignTask } from '../lib/api'
import { BUILT_IN_TEMPLATES } from '../lib/task-templates'
import type { SignTask, AccountInfo } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
import { useTaskListRuntime } from '../composables/useTaskListRuntime'
import type { TaskUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'
import CloneTaskModal from '../components/tasks/CloneTaskModal.vue'
import TaskListCard from '../components/tasks/TaskListCard.vue'
import { devLog } from '../lib/devLog'
import {
  filterTasksByModeAndQuery,
  hasActiveListFilters,
  type TaskListModeFilter,
} from '../lib/task-list-filter'

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
/** 模式筛选：全部 / 仅监听 / 仅定时 */
const modeFilter = ref<TaskListModeFilter>('all')
const selectedCount = computed(() => selectedTaskIds.value.size)
const cloneBusy = ref(false)
const showCloneModal = ref(false)
const cloneSource = ref<TaskUiItem | null>(null)
const showTemplateMenu = ref(false)

const toggleTemplateMenu = (e?: Event) => {
  e?.stopPropagation()
  showTemplateMenu.value = !showTemplateMenu.value
}

const pickTemplate = (templateId: string) => {
  showTemplateMenu.value = false
  handleCreateFromTemplate(templateId)
}
const filteredTasks = computed(() =>
  filterTasksByModeAndQuery(tasks.value, modeFilter.value, searchQuery.value),
)
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

/** 是否有激活中的列表筛选（搜索 / 模式 / 账号深链） */
const hasListFilters = computed(() =>
  hasActiveListFilters(searchQuery.value, modeFilter.value, accountFilter.value),
)

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
      toast.success(t('tasks.batchSuccessDetail', { ok: res.success_count }))
    } else {
      const failedNames = (res.results || [])
        .filter((r) => !r.success)
        .map((r) => r.name)
        .filter(Boolean)
        .slice(0, 3)
      const detail = failedNames.length
        ? ` · ${failedNames.join(', ')}${(res.fail_count || 0) > failedNames.length ? '…' : ''}`
        : ''
      toast.error(
        `${t('tasks.batchPartialDetail', { ok: res.success_count, fail: res.fail_count })}${detail}`,
      )
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

const {
  cancelBusyKey,
  afterTasksLoaded,
  taskActiveRuns,
  taskActiveRun,
  activeRunBadgeText,
  activeRunTooltip,
  taskHasInvalidAccount,
  handleCancelRun,
  loadAccountStatusMap,
} = useTaskListRuntime({
  tasks,
  listenTaskCount,
  accountFilter,
  getTaskAccountName,
})

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

    await afterTasksLoaded()
  } catch (e) {
    devLog.error('Failed to fetch tasks', e)
    toast.error(getLocalizedErrorMessage(e, t, t('tasks.loadFailed')))
    tasks.value = []
  } finally {
    pageLoading.value = false
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
  void loadAccountStatusMap()
})

watch(() => route.query.task, () => applyRouteQueryFilters())
watch(
  () => [route.query.tab, route.query.task, tasks.value.length] as const,
  () => applyLogsDeepLink(),
)

watch(() => route.query.account, () => {
  loadTasks()
})

const openCloneModal = (task: TaskUiItem) => {
  cloneSource.value = task
  showCloneModal.value = true
}

const closeCloneModal = () => {
  showCloneModal.value = false
  cloneSource.value = null
}

const submitClone = async (rawName: string) => {
  if (cloneBusy.value || !cloneSource.value) return
  const newName = rawName.trim()
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

/** 清除搜索、模式筛选与账号深链（与 chip / 空态「清除筛选」一致） */
const clearListFilters = () => {
  searchQuery.value = ''
  modeFilter.value = 'all'
  if (accountFilter.value) clearAccountFilter()
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
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="runBatch('enable')">
          <Power class="w-3.5 h-3.5" />
          {{ t('tasks.batchEnable') }}
        </button>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="runBatch('disable')">
          <Pause class="w-3.5 h-3.5" />
          {{ t('tasks.batchDisable') }}
        </button>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="runBatch('run')">
          <Play class="w-3.5 h-3.5" />
          {{ t('tasks.batchRun') }}
        </button>
        <button type="button" class="ui-btn-danger !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="runBatch('delete')">
          <Trash2 class="w-3.5 h-3.5" />
          {{ t('tasks.batchDelete') }}
        </button>
        <div class="relative ml-auto" @click.stop>
          <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" @click="toggleTemplateMenu">
            <LayoutTemplate class="w-3.5 h-3.5" />
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
      <!-- 激活中的筛选：chip 一键清除 -->
      <div
        v-if="hasListFilters"
        class="flex flex-wrap items-center gap-1.5 pt-0.5 border-t border-gray-100 dark:border-gray-800/50"
      >
        <span class="text-[10px] text-gray-400 shrink-0">{{ t('common.activeFilters') }}</span>
        <button
          v-if="searchQuery.trim()"
          type="button"
          class="inline-flex items-center gap-1 max-w-[14rem] px-2 py-0.5 rounded-sm text-[11px] bg-sky-50 text-sky-800 border border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50"
          :title="t('common.clearFilters')"
          @click="searchQuery = ''"
        >
          <span class="truncate">{{ t('common.search') }}: {{ searchQuery.trim() }}</span>
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="modeFilter === 'listen'"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-orange-50 text-orange-800 border border-orange-100 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-800/50"
          @click="modeFilter = 'all'"
        >
          {{ t('tasks.filterListen') }}
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="modeFilter === 'scheduled'"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-violet-50 text-violet-800 border border-violet-100 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-800/50"
          @click="modeFilter = 'all'"
        >
          {{ t('tasks.filterScheduled') }}
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="accountFilter"
          type="button"
          class="inline-flex items-center gap-1 max-w-[12rem] px-2 py-0.5 rounded-sm text-[11px] bg-sky-50 text-sky-800 border border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50"
          :title="t('tasks.clearAccountFilter')"
          @click="clearAccountFilter"
        >
          <span class="truncate">{{ t('tasks.accountFilter') }}: {{ accountFilter }}</span>
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          type="button"
          class="text-[11px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 underline-offset-2 hover:underline ml-auto shrink-0"
          @click="clearListFilters"
        >
          {{ t('common.clearFilters') }}
        </button>
      </div>
    </div>

    <div v-if="filteredTasks.length === 0" class="ui-empty !py-12">
      <template v-if="tasks.length > 0 && hasListFilters">
        <p class="ui-empty-title !text-gray-500 font-normal">{{ t('common.filterNoResults') }}</p>
        <p class="ui-empty-desc mb-3">{{ t('common.filterNoResultsHint') }}</p>
        <button type="button" class="ui-btn-secondary !text-xs !px-3 !py-2" @click="clearListFilters">
          {{ t('common.clearAllFilters') }}
        </button>
      </template>
      <template v-else-if="accountFilter && tasks.length === 0">
        <p class="ui-empty-title !text-gray-500 font-normal">{{ t('common.filterNoResults') }}</p>
        <p class="ui-empty-desc mb-3">{{ t('tasks.accountFilterEmpty') }}</p>
        <button type="button" class="ui-btn-secondary !text-xs !px-3 !py-2" @click="clearAccountFilter">
          {{ t('tasks.clearAccountFilter') }}
        </button>
      </template>
      <p v-else class="ui-empty-desc">{{ t('common.noData') }}</p>
    </div>

    <TaskListCard
      v-for="task in filteredTasks"
      :key="task.id"
      :task="task"
      :selected="selectedTaskIds.has(task.id)"
      :clone-busy="cloneBusy"
      :cancel-busy-key="cancelBusyKey"
      :run-menu-open="runMenuTask === task"
      :run-menu-accounts="runMenuAccounts"
      :task-active-run="taskActiveRun(task)"
      :task-active-runs="taskActiveRuns(task)"
      :active-run-badge-text="activeRunBadgeText(task)"
      :active-run-tooltip="activeRunTooltip(task)"
      :has-invalid-account="taskHasInvalidAccount(task)"
      @toggle-select="toggleSelectTask"
      @toggle-enabled="handleToggleEnabled"
      @cancel-run="handleCancelRun"
      @run="handleRun"
      @run-account="(task, acc) => doRun(task, acc)"
      @open-logs="(task, tab) => openLogs(task, tab ?? null)"
      @clone="openCloneModal"
      @edit="openEdit"
      @delete="handleDelete"
    />
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

    <CloneTaskModal
      :isOpen="showCloneModal"
      :source-name="cloneSource?.name || ''"
      :busy="cloneBusy"
      @close="closeCloneModal"
      @submit="submitClone"
    />
  </div>
</template>
