<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Plus, Radio, Clock, Shuffle, X, Zap } from 'lucide-vue-next'
import { listSignTasks } from '../lib/api'
import { withToken } from '../lib/api/core'
import { useLatestResponseGuard } from '../lib/latest-response'
import { BUILT_IN_TEMPLATES } from '../lib/task-templates'
import type { SignTask } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useAccountsStore } from '../stores/accounts'
import { useTaskListRuntime } from '../composables/useTaskListRuntime'
import { useTaskListActions } from '../composables/useTaskListActions'
import type { TaskUiItem } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'
import CloneTaskModal from '../components/tasks/CloneTaskModal.vue'
import TaskListCard from '../components/tasks/TaskListCard.vue'
import TaskListToolbar from '../components/tasks/TaskListToolbar.vue'
import FilterEmptyState from '../components/FilterEmptyState.vue'
import PageRetry from '../components/PageRetry.vue'
import { devLog } from '../lib/devLog'
import {
  filterTasksByModeAndQuery,
  hasActiveListFilters,
  type TaskListModeFilter,
} from '../lib/task-list-filter'
import {
  mapSignTaskToListFields,
  withModeIcon,
  resolveTaskAccountName,
} from '../lib/task-list-map'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const toast = useToast()
const accountsStore = useAccountsStore()
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

const allAccounts = ref<string[]>([])
const selectedTaskIds = ref<Set<string>>(new Set())
const searchQuery = ref('')
/** 模式筛选：全部 / 仅监听 / 仅定时 */
const modeFilter = ref<TaskListModeFilter>('all')
const selectedCount = computed(() => selectedTaskIds.value.size)
const showTemplateMenu = ref(false)

// Esc 关闭空态模板菜单：焦点通常在触发按钮上，事件不经过菜单容器，
// 需挂 window 级监听；与工具栏下拉的关闭语义一致。
// 用 watch 统一挂载/卸载，任何置 false 的路径都会自动清理监听
const closeTemplateMenuOnEsc = (e: KeyboardEvent) => {
  if (e.key !== 'Escape') return
  if (!showTemplateMenu.value) return
  e.stopPropagation()
  showTemplateMenu.value = false
}
watch(showTemplateMenu, (open) => {
  if (open) window.addEventListener('keydown', closeTemplateMenuOnEsc)
  else window.removeEventListener('keydown', closeTemplateMenuOnEsc)
})
onUnmounted(() => window.removeEventListener('keydown', closeTemplateMenuOnEsc))

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

/** 是否有激活中的列表筛选（搜索 / 模式 / 账号深链） */
const hasListFilters = computed(() =>
  hasActiveListFilters(searchQuery.value, modeFilter.value, accountFilter.value),
)

const loadAllAccounts = async () => {
  return withToken(async () => {
    try {
      // 走共享 store：TTL 命中时与 Dashboard/Logs 复用同一缓存
      const list = await accountsStore.ensureAccounts()
      allAccounts.value = (list || []).map((a) => a.name)
    } catch (e) {
      devLog.warn('加载账号筛选列表失败', e)
    }
  })
}

const {
  cancelBusyKey,
  afterTasksLoaded,
  runCardProps,
  handleCancelRun,
  loadAccountStatusMap,
} = useTaskListRuntime({
  tasks,
  listenTaskCount,
  accountFilter,
  getTaskAccountName: resolveTaskAccountName,
})

// 请求序号守卫：丢弃过期响应，避免快速切换账号筛选时慢响应覆盖新结果
const tasksGuard = useLatestResponseGuard()

const loadFailed = ref(false)

const loadTasks = async () => {
  return withToken(async (token) => {
    const seq = tasksGuard.next()
    pageLoading.value = true
    try {
      const accountName = route.query.account as string | undefined
      const res = await listSignTasks(token, accountName)
      if (!tasksGuard.isCurrent(seq)) return // 过期响应：筛选已变化，丢弃
      loadFailed.value = false
      const labels = {
        noTarget: t('tasks.noTarget'),
        listenMode: t('tasks.listenMode'),
        notExecuted: t('tasks.notExecuted'),
        continuousRunning: t('tasks.continuousRunning'),
        paused: t('tasks.paused'),
        success: t('tasks.success'),
        failed: t('tasks.failed'),
        chatFallbackPrefix: t('tasks.chatPrefix'),
      }
      const iconByKind = { clock: Clock, radio: Radio, shuffle: Shuffle } as const
      tasks.value = res.map((task: SignTask) => {
        const fields = mapSignTaskToListFields(task, labels)
        return withModeIcon(fields, iconByKind[fields.modeIconKind])
      })

      await afterTasksLoaded()
    } catch (e: unknown) {
      if (!tasksGuard.isCurrent(seq)) return
      devLog.error('Failed to fetch tasks', e)
      notifyApiError(e, 'tasks.loadFailed')
      loadFailed.value = true
      tasks.value = []
    } finally {
      if (tasksGuard.isCurrent(seq)) pageLoading.value = false
    }
  })
}

const {
  batchBusy,
  cloneBusy,
  toggleBusyKey,
  runBusyKey,
  deleteBusyKey,
  showCloneModal,
  cloneSource,
  runMenuTask,
  runMenuAccounts,
  clearSelection,
  runBatch,
  openCloneModal,
  closeCloneModal,
  submitClone,
  handleDelete,
  handleToggleEnabled,
  handleRun,
  doRun,
  closeRunMenu: closeRunMenuOnly,
} = useTaskListActions({
  tasks,
  selectedTaskIds,
  allAccounts,
  selectedCount,
  loadTasks,
  openLogsAfterRun: (task, accountName) => {
    logsRunAccount.value = accountName
    logsTask.value = task
    showLogsModal.value = true
  },
})

const closeRunMenu = () => {
  closeRunMenuOnly()
  showTemplateMenu.value = false
}

// Esc 关闭运行账号菜单：键盘用户打开多账号运行菜单后可用 Esc 退出；
// 挂在 runMenuTask 变化上，任何置 null 的路径都会自动清理监听
const closeRunMenuOnEsc = (e: KeyboardEvent) => {
  if (e.key !== 'Escape') return
  if (!runMenuTask.value) return
  e.stopPropagation()
  closeRunMenu()
}
watch(runMenuTask, (task) => {
  if (task) window.addEventListener('keydown', closeRunMenuOnEsc)
  else window.removeEventListener('keydown', closeRunMenuOnEsc)
})
onUnmounted(() => window.removeEventListener('keydown', closeRunMenuOnEsc))

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

    <!-- 首屏加载失败：错误态而非空列表，避免误导为暂无任务 -->
    <div v-else-if="loadFailed && tasks.length === 0" class="max-w-xl mx-auto">
      <PageRetry @retry="loadTasks" />
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
          <Zap class="w-8 h-8" />
        </div>
        <p class="ui-empty-title">{{ t('tasks.empty') }}</p>
        <p class="ui-empty-desc mb-4">{{ t('tasks.emptyHint') }}</p>
        <div class="flex flex-wrap items-center justify-center gap-2">
          <div class="relative" @click.stop>
            <button type="button" class="ui-btn-secondary !text-xs !px-3 !py-2" :aria-expanded="showTemplateMenu" aria-haspopup="menu" @click="toggleTemplateMenu">
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
    <TaskListToolbar
      v-model:search-query="searchQuery"
      v-model:mode-filter="modeFilter"
      :all-selected="allSelected"
      :selected-count="selectedCount"
      :batch-busy="batchBusy"
      :listen-task-count="listenTaskCount"
      :has-list-filters="hasListFilters"
      :account-filter="accountFilter"
      :show-template-menu="showTemplateMenu"
      @toggle-select-all="toggleSelectAll"
      @clear-selection="clearSelection"
      @batch="runBatch"
      @toggle-template-menu="toggleTemplateMenu"
      @pick-template="pickTemplate"
      @open-add="openAddBlank"
      @clear-list-filters="clearListFilters"
      @clear-account-filter="clearAccountFilter"
    />

    <div v-if="filteredTasks.length === 0" class="ui-empty !py-12">
      <FilterEmptyState
        v-if="hasListFilters"
        :title="t('common.filterNoResults')"
        :hint="t('common.filterNoResultsHint')"
        :action-text="t('common.clearAllFilters')"
        @action="clearListFilters"
      />
      <p v-else class="ui-empty-desc">{{ t('common.noData') }}</p>
    </div>

    <TaskListCard
      v-for="task in filteredTasks"
      :key="task.id"
      :task="task"
      :selected="selectedTaskIds.has(task.id)"
      :clone-busy="cloneBusy"
      :cancel-busy-key="cancelBusyKey"
      :toggle-busy-key="toggleBusyKey"
      :run-busy-key="runBusyKey"
      :delete-busy-key="deleteBusyKey"
      :run-menu-open="runMenuTask === task"
      :run-menu-accounts="runMenuAccounts"
      v-bind="runCardProps(task)"
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
