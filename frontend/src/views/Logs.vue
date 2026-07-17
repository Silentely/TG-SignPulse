<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Trash2, RefreshCw } from 'lucide-vue-next'
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
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
import type { TaskLogUiItem, LoginLogUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import Modal from '../components/Modal.vue'
import CustomSelect from '../components/CustomSelect.vue'
import DatePicker from '../components/DatePicker.vue'
import FlowLogViewer from '../components/FlowLogViewer.vue'

const { locale, t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()
const route = useRoute()

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

/** 原始任务日志（服务端结果），客户端再做名称/状态筛选 */
const rawTaskLogs = ref<TaskHistoryLog[]>([])
const pageLoading = ref(true)
const clearing = ref(false)
const accountsList = ref<string[]>([])
const selectedLog = ref<TaskLogUiItem | null>(null)
const logDetail = ref<TaskHistoryLogDetail | null>(null)
const detailLoading = ref(false)

const accountOptions = computed(() => [
  { label: t('logs.allAccounts'), value: '' },
  ...accountsList.value.map(a => ({ label: a, value: a }))
])

const statusOptions = computed(() => [
  { label: t('logs.allStatus'), value: '' },
  { label: t('logs.success'), value: 'success' },
  { label: t('logs.failed'), value: 'error' }
])

const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  const loc = locale.value === 'zh' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(loc, { hour12: false })
}

const failureCategoryLabel = (cat?: string | null) => {
  if (!cat || cat === 'none' || cat === 'unknown') return ''
  const key = `dashboard.failCat.${cat}`
  const label = t(key)
  return label === key ? cat : label
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
      filterStatus.value === 'success' ? l.success : !l.success
    )
  }
  return filtered.map(toTaskUi)
})

const loginLogs = ref<LoginLogUiItem[]>([])

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

// 切换 Tab / 账号 / 日期 → 重新请求服务端
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

  // 等待列表加载后匹配并打开详情
  const match = rawTaskLogs.value.find(
    (l) => l.task_name === taskQ && (l.created_at === atQ || l.created_at.startsWith(atQ.slice(0, 19)))
  ) || rawTaskLogs.value.find((l) => l.task_name === taskQ)

  if (match) {
    filterTask.value = taskQ
    await openLogDetail(toTaskUi(match))
  }
}

onMounted(async () => {
  const queryAccount = route.query.account as string | undefined
  if (queryAccount) {
    filterAccount.value = queryAccount
  }
  const queryTask = route.query.task as string | undefined
  if (queryTask) {
    filterTask.value = queryTask
  }
  loadAccounts()
  await loadLogs()
  await tryOpenFromQuery()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tabs + actions -->
    <div class="flex items-end justify-between gap-4 mb-4 border-b border-gray-200 dark:border-gray-800/60">
      <div class="flex gap-1 sm:gap-6">
        <button
          type="button"
          class="px-1 pb-2.5 text-sm font-medium transition-colors border-b-2"
          :class="activeTab === 'tasks' ? 'border-sky-500 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = 'tasks'"
        >
          {{ t('logs.taskLogs') }}
        </button>
        <button
          type="button"
          class="px-1 pb-2.5 text-sm font-medium transition-colors border-b-2"
          :class="activeTab === 'login' ? 'border-sky-500 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = 'login'"
        >
          {{ t('logs.auditLogs') }}
        </button>
      </div>

      <div class="flex items-center gap-0.5 pb-1.5">
        <button
          type="button"
          class="ui-icon-btn disabled:opacity-50"
          :title="t('common.refresh')"
          :disabled="pageLoading"
          @click="loadLogs"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': pageLoading }" />
        </button>
        <button
          type="button"
          class="ui-icon-btn hover:!text-rose-600 dark:hover:!text-rose-400 hover:!bg-rose-50 dark:hover:!bg-rose-950/30 disabled:opacity-50"
          :title="t('logs.clear')"
          :disabled="clearing || pageLoading"
          @click="handleClear"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="ui-card p-3 mb-5">
      <div
        class="grid gap-3"
        :class="activeTab === 'tasks' ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-1 sm:grid-cols-2'"
      >
        <template v-if="activeTab === 'tasks'">
          <input
            v-model="filterTask"
            type="text"
            :placeholder="t('logs.taskName')"
            class="ui-input"
            :aria-label="t('logs.taskName')"
          >
          <CustomSelect v-model="filterAccount" :options="accountOptions" :ariaLabel="t('logs.colAccount')" />
          <CustomSelect v-model="filterStatus" :options="statusOptions" :ariaLabel="t('logs.colStatus')" />
        </template>
        <DatePicker v-model="filterDate" />
      </div>
    </div>

    <!-- Logs List -->
    <div class="ui-card p-3 sm:p-5 flex-1 min-h-[500px] overflow-y-auto">
      <div v-if="pageLoading" class="ui-page-loading">
        <div class="ui-spinner" aria-hidden="true" />
      </div>

      <!-- Task logs -->
      <div v-else-if="activeTab === 'tasks'" class="text-xs space-y-0">
        <div v-if="logs.length === 0" class="ui-empty py-16">
          <p class="ui-empty-title !text-gray-500 font-normal">{{ t('logs.empty') }}</p>
          <p class="ui-empty-desc">{{ t('logs.emptyHint') }}</p>
        </div>
        <div v-else class="overflow-x-auto">
          <!-- header -->
          <div class="ui-table-head hidden sm:flex">
            <span class="w-[140px] shrink-0">{{ t('logs.colTime') }}</span>
            <span class="w-24 shrink-0">{{ t('logs.colAccount') }}</span>
            <span class="w-28 shrink-0">{{ t('logs.colTask') }}</span>
            <span class="w-16 shrink-0">{{ t('logs.colStatus') }}</span>
            <span class="flex-1">{{ t('logs.colSummary') }}</span>
          </div>
          <div
            v-for="log in logs"
            :key="`${log.account}-${log.task}-${log.created_at}-${log.id}`"
            class="ui-list-row flex items-center gap-3 px-2 py-2 cursor-pointer rounded-sm"
            @click="openLogDetail(log)"
          >
            <span class="font-mono text-gray-500 dark:text-gray-600 shrink-0 w-[140px] text-[11px]">{{ log.time }}</span>
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
              class="truncate flex-1 min-w-0"
              :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
              :title="log.text"
            >
              {{ log.text }}
            </span>
            <span
              v-if="log.status === 'error' && failureCategoryLabel(log.failure_category)"
              class="ui-badge ui-badge-warn hidden md:inline-flex shrink-0"
            >
              {{ failureCategoryLabel(log.failure_category) }}
            </span>
            <span
              v-if="log.flow_line_count > 0"
              class="hidden sm:inline shrink-0 text-[10px] text-gray-400 font-mono"
            >
              {{ log.flow_line_count }}{{ t('logs.linesSuffix') }}
            </span>
          </div>
        </div>
      </div>

      <!-- Login audit -->
      <div v-else class="text-xs space-y-0">
        <div v-if="loginLogs.length === 0" class="ui-empty py-16">
          <p class="ui-empty-title !text-gray-500 font-normal">{{ t('logs.emptyLogin') }}</p>
          <p class="ui-empty-desc">{{ t('logs.emptyLoginHint') }}</p>
        </div>
        <div v-else class="overflow-x-auto">
          <div class="ui-table-head hidden sm:flex">
            <span class="w-[140px] shrink-0">{{ t('logs.colTime') }}</span>
            <span class="w-24 shrink-0">{{ t('logs.colUser') }}</span>
            <span class="w-32 shrink-0">{{ t('logs.colIp') }}</span>
            <span class="w-16 shrink-0">{{ t('logs.colStatus') }}</span>
            <span class="flex-1">{{ t('logs.colSummary') }}</span>
          </div>
          <div
            v-for="log in loginLogs"
            :key="log.id"
            class="ui-list-row flex items-center gap-3 px-2 py-2 rounded-sm"
          >
            <span class="font-mono text-gray-500 dark:text-gray-600 shrink-0 w-[140px] text-[11px]">{{ log.time }}</span>
            <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.username }}</span>
            <span class="text-gray-500 shrink-0 w-32 truncate font-mono text-[11px]">{{ log.ip }}</span>
            <span
              class="ui-badge shrink-0"
              :class="log.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
            >
              <span class="ui-badge-dot" />
              {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
            </span>
            <span
              class="truncate flex-1"
              :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
            >
              {{ log.text }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <Modal
      :isOpen="!!selectedLog"
      :title="t('logs.detailTitle')"
      maxWidthClass="max-w-2xl"
      @close="selectedLog = null; logDetail = null"
    >
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="flex items-center gap-3 flex-wrap">
          <span
            class="ui-badge text-xs"
            :class="selectedLog.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}
          </span>
          <span
            v-if="selectedLog.status === 'error' && failureCategoryLabel(selectedLog.failure_category || logDetail?.failure_category)"
            class="ui-badge ui-badge-warn"
          >
            {{ failureCategoryLabel(selectedLog.failure_category || logDetail?.failure_category) }}
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
        </div>

        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div v-if="detailLoading" class="flex items-center gap-2 text-xs text-gray-500 py-6 justify-center">
            <span class="ui-spinner !w-4 !h-4 !border-2" />
            {{ t('common.loading') }}
          </div>

          <FlowLogViewer
            v-else
            :lines="logDetail?.flow_logs || []"
            :last-target-message="logDetail?.last_target_message || logDetail?.bot_message || selectedLog.text"
            :truncated="!!logDetail?.flow_truncated"
            :empty-text="logDetail?.message || selectedLog.text || t('logs.noDetail')"
          />
        </div>
      </div>
    </Modal>
  </div>
</template>
