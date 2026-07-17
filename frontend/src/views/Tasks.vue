<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, Radio, Clock, Shuffle, Power, Search } from 'lucide-vue-next'
import { listSignTasks, deleteSignTask, startSignTaskRun, listAccounts, toggleSignTaskEnabled, batchSignTasks } from '../lib/api'
import type { SignTask, AccountInfo } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
import type { TaskUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'
import { devLog } from '../lib/devLog'

const route = useRoute()
const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()
const tasks = ref<TaskUiItem[]>([])
const pageLoading = ref(true)
const showAddModal = ref(false)
const showEditModal = ref(false)
const showLogsModal = ref(false)
const editingTask = ref<SignTask | null>(null)
const logsTask = ref<TaskUiItem | null>(null)
const logsRunAccount = ref<string>('')  // Account that just executed the task

// Account selection for run
const runMenuTask = ref<TaskUiItem | null>(null)
const runMenuAccounts = ref<string[]>([])
const allAccounts = ref<string[]>([])
const selectedTaskIds = ref<Set<string>>(new Set())
const batchBusy = ref(false)
const searchQuery = ref('')
const selectedCount = computed(() => selectedTaskIds.value.size)
const filteredTasks = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return tasks.value
  return tasks.value.filter(
    (task) =>
      task.name.toLowerCase().includes(q) ||
      task.targetStr.toLowerCase().includes(q) ||
      task.scheduleMode.toLowerCase().includes(q) ||
      task.lastRunStr.toLowerCase().includes(q)
  )
})
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
      const firstChat = task.chats && task.chats.length > 0 ? task.chats[0] : null
      const targetStr = firstChat ? `${firstChat.chat_id}${firstChat.message_thread_id ? '|' + firstChat.message_thread_id : ''}` : t('tasks.noTarget')
      
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

onMounted(() => {
  loadTasks()
  loadAllAccounts()
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
}

const openEdit = (task: TaskUiItem) => {
  editingTask.value = task.raw
  showEditModal.value = true
}

const openLogs = (task: TaskUiItem) => {
  logsRunAccount.value = ''  // No specific run account, show aggregated history
  logsTask.value = task
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
    <div v-else-if="tasks.length === 0" class="ui-empty">
      <div class="ui-empty-icon">
        <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      </div>
      <p class="ui-empty-title">{{ t('tasks.empty') }}</p>
      <p class="ui-empty-desc mb-4">{{ t('tasks.emptyHint') }}</p>
      <button type="button" class="ui-btn-primary !text-xs !px-3 !py-2" @click="showAddModal = true">
        <Plus class="w-3.5 h-3.5" /> {{ t('taskModal.addTitle') }}
      </button>
    </div>

    <div v-else class="flex flex-col gap-3 pb-24">
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
              class="ui-badge ui-badge-neutral !text-[11px] font-mono max-w-[14rem] truncate"
              :title="task.targetStr"
            >
              {{ task.targetStr }}
            </span>
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
        <div class="relative" @click.stop>
          <button
            type="button"
            class="inline-flex items-center gap-1 px-2 py-1.5 rounded-sm text-xs transition-colors"
            :class="task.raw.execution_mode === 'listen'
              ? 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
              : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04]'"
            :title="t('tasks.executeNow')"
            :disabled="task.raw.execution_mode === 'listen'"
            @click="task.raw.execution_mode !== 'listen' && handleRun(task)"
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
        @click="showAddModal = true"
      >
        <Plus class="w-5 h-5" />
      </button>
    </div>

    <!-- Modals -->
    <AddTaskModal :isOpen="showAddModal" @close="showAddModal = false" @success="loadTasks" />
    <EditTaskModal v-if="editingTask" :isOpen="showEditModal" :task="editingTask" @close="showEditModal = false" @success="loadTasks" />
    <TaskLogsModal :isOpen="showLogsModal" :task="logsTask" :runAccount="logsRunAccount" @close="showLogsModal = false" />
  </div>
</template>
