<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, Radio, Clock, Shuffle, Power } from 'lucide-vue-next'
import { listSignTasks, deleteSignTask, startSignTaskRun, listAccounts, toggleSignTaskEnabled, batchSignTasks } from '../lib/api'
import type { SignTask, AccountInfo } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useAuthStore } from '../stores/auth'
import type { TaskUiItem } from '../lib/types'
import { getErrorMessage } from '../lib/types'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'

const route = useRoute()
const { t } = useI18n()
const toast = useToast()
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
const selectedCount = computed(() => selectedTaskIds.value.size)
const allSelected = computed(() => tasks.value.length > 0 && selectedTaskIds.value.size === tasks.value.length)

const toggleSelectTask = (id: string) => {
  const next = new Set(selectedTaskIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedTaskIds.value = next
}
const toggleSelectAll = () => {
  if (allSelected.value) {
    selectedTaskIds.value = new Set()
  } else {
    selectedTaskIds.value = new Set(tasks.value.map((t) => t.id))
  }
}
const clearSelection = () => { selectedTaskIds.value = new Set() }

const runBatch = async (action: 'enable' | 'disable' | 'delete' | 'run') => {
  if (!selectedCount.value || batchBusy.value) return
  if (action === 'delete' && !confirm(`${t('tasks.batchDeleteConfirm')} (${selectedCount.value})`)) return
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
    toast.error(getErrorMessage(e, t('tasks.batchFailed')))
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
    console.error('Failed to fetch tasks', e)
    toast.error(getErrorMessage(e, t('tasks.loadFailed')))
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
  if (!confirm(`${t('tasks.deleteConfirm')} ${task.name} ?`)) return
  const token = authStore.token || ''
  try {
    const accountName = getTaskAccountName(task.raw) || undefined
    await deleteSignTask(token, task.name, accountName)
    toast.success(t('tasks.deleteSuccess'))
    await loadTasks()
  } catch (e: unknown) {
    toast.error(`${t('tasks.deleteFailed')}: ${getErrorMessage(e) || t('tasks.unknownError')}`)
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
    toast.error(`${t('tasks.toggleFailed')}: ${getErrorMessage(e) || t('tasks.unknownError')}`)
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
    toast.error(`${t('tasks.triggerFailed')}: ${getErrorMessage(e) || t('tasks.unknownError')}`)
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
    <!-- Page Loading -->
    <div v-if="pageLoading" class="flex items-center justify-center py-20">
      <svg class="animate-spin w-6 h-6 text-gray-400" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
    </div>

    <!-- Empty State -->
    <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-20 text-center">
      <div class="w-16 h-16 bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 flex items-center justify-center mb-4">
        <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      </div>
      <p class="text-sm text-gray-900 dark:text-gray-100 font-medium mb-1">{{ t('tasks.empty') }}</p>
      <p class="text-xs text-gray-500">{{ t('tasks.emptyHint') }}</p>
    </div>

    <div v-else class="flex flex-col gap-2 pb-20">
    <!-- 批量操作栏 -->
    <div class="flex flex-wrap items-center gap-2 p-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60">
      <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer">
        <input type="checkbox" :checked="allSelected" @change="toggleSelectAll" class="rounded border-gray-300" />
        {{ t('tasks.selectAll') }}
      </label>
      <span v-if="selectedCount" class="text-xs text-gray-500">{{ t('tasks.selectedCount') }}: {{ selectedCount }}</span>
      <div class="flex-1" />
      <button type="button" :disabled="!selectedCount || batchBusy" @click="runBatch('enable')" class="px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800">{{ t('tasks.batchEnable') }}</button>
      <button type="button" :disabled="!selectedCount || batchBusy" @click="runBatch('disable')" class="px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800">{{ t('tasks.batchDisable') }}</button>
      <button type="button" :disabled="!selectedCount || batchBusy" @click="runBatch('run')" class="px-2 py-1 text-xs border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800">{{ t('tasks.batchRun') }}</button>
      <button type="button" :disabled="!selectedCount || batchBusy" @click="runBatch('delete')" class="px-2 py-1 text-xs border border-rose-200 text-rose-600 dark:border-rose-800 disabled:opacity-40 hover:bg-rose-50 dark:hover:bg-rose-900/20">{{ t('tasks.batchDelete') }}</button>
    </div>
    <div
      v-for="task in tasks" :key="task.id"
      class="group flex flex-col sm:flex-row sm:items-center p-4 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 hover:border-gray-300 dark:hover:border-gray-700 transition-colors"
      :class="{ 'opacity-50': !task.enabled, 'ring-1 ring-sky-400/50': selectedTaskIds.has(task.id) }"
    >
      <!-- Mobile Layout: Avatar + Name + Status -->
      <div class="flex-1 flex gap-3 w-full overflow-hidden">
        <label class="self-center shrink-0 cursor-pointer" @click.stop>
          <input type="checkbox" :checked="selectedTaskIds.has(task.id)" @change="toggleSelectTask(task.id)" class="rounded border-gray-300" />
        </label>
        <!-- Avatar - spans both rows, shown on both mobile and PC -->
        <div class="w-9 h-9 sm:w-10 sm:h-10 shrink-0 bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-[9px] text-gray-500 border border-gray-200 dark:border-gray-700 overflow-hidden rounded-sm self-center">
          <img v-if="task.chatAvatarUrl" :src="task.chatAvatarUrl" class="w-full h-full object-cover" />
          <component v-else :is="task.modeIcon" class="w-4 h-4 sm:w-5 sm:h-5" />
        </div>

        <!-- Right side: Name row + Badges row -->
        <div class="flex-1 flex flex-col gap-1.5 min-w-0">
          <!-- Row 1: Name + Last Run (mobile) / Name (PC) -->
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-medium text-gray-900 dark:text-gray-200 truncate" :title="task.name">{{ task.name }}</span>
            <!-- Last Run on mobile only -->
            <span class="sm:hidden px-2 py-0.5 rounded text-[10px] border shrink-0"
                   :title="task.lastRunStr"
                   :class="task.isListenMode && task.lastRunSuccess === null ? 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800/50' :
                           task.lastRunSuccess === null ? 'bg-gray-50 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700' :
                           (task.lastRunSuccess ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50' : 
                           'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50')">
               {{ task.lastRunStr }}
            </span>
          </div>

          <!-- Row 2 (PC): Badges row - Schedule + Target + Last Run -->
          <div class="hidden sm:flex items-center gap-2">
            <!-- Schedule badge -->
            <span class="px-2 py-0.5 rounded text-xs font-mono bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-100 dark:border-blue-800/50 truncate" :title="task.scheduleMode">
              {{ task.scheduleMode }}
            </span>
            <!-- Target badge -->
            <span class="px-2 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border border-gray-200 dark:border-gray-700/50 truncate" :title="task.targetStr">
              {{ task.targetStr }}
            </span>
            <!-- Last Run badge (PC) -->
            <span class="px-2 py-0.5 rounded text-xs border truncate"
                  :title="task.lastRunStr"
                  :class="task.isListenMode && task.lastRunSuccess === null ? 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800/50' :
                          task.lastRunSuccess === null ? 'bg-gray-50 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700' :
                          (task.lastRunSuccess ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50' : 
                          'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50')">
              {{ task.lastRunStr }}
            </span>
          </div>

          <!-- Mobile Second Row: Schedule + Target -->
          <div class="flex sm:hidden items-center gap-2 w-full overflow-hidden">
            <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-100 dark:border-blue-800/50 truncate" :title="task.scheduleMode">
              {{ task.scheduleMode }}
            </span>
            <span class="px-2 py-0.5 rounded text-[10px] font-mono bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border border-gray-200 dark:border-gray-700/50 truncate" :title="task.targetStr">
              {{ task.targetStr }}
            </span>
          </div>
        </div>
      </div>

      <!-- Divider for Actions on Mobile -->
      <div class="sm:hidden w-full border-t border-dashed border-gray-200 dark:border-gray-700 my-3"></div>

      <!-- Actions Area -->
      <div class="flex items-center justify-between sm:justify-end gap-2 sm:gap-1.5 mt-2 sm:mt-0 transition-opacity duration-200 shrink-0 sm:pl-4">
        <!-- Toggle enabled/paused -->
        <button
          @click="handleToggleEnabled(task)"
          class="flex-1 sm:flex-none flex justify-center items-center gap-1 px-2 py-1.5 rounded transition-colors text-xs"
          :class="task.enabled ? 'text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20' : 'text-gray-400 dark:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800'"
          :title="task.enabled ? t('tasks.pause') : t('tasks.resume')"
        >
          <Power class="w-3.5 h-3.5" />
          <span class="text-xs">{{ task.enabled ? t('tasks.pause') : t('tasks.resume') }}</span>
        </button>
        <!-- Execute (disabled for listen mode) -->
        <div class="relative flex-1 sm:flex-none" @click.stop>
          <button
            @click="task.raw.execution_mode !== 'listen' && handleRun(task)"
            class="w-full sm:w-auto flex justify-center items-center gap-1 px-2 py-1.5 rounded transition-colors text-xs"
            :class="task.raw.execution_mode === 'listen' ? 'text-gray-300 dark:text-gray-700 cursor-not-allowed' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800'"
            :title="t('tasks.executeNow')"
            :disabled="task.raw.execution_mode === 'listen'"
          >
            <Play class="w-3.5 h-3.5" />
            <span class="text-xs">{{ t('tasks.execute') }}</span>
          </button>
          <!-- Account selection dropdown -->
          <div v-if="runMenuTask === task" class="absolute top-full left-0 sm:right-0 sm:left-auto mt-1 z-50 min-w-[140px] bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded shadow-lg py-1">
            <div class="px-3 py-1.5 text-[10px] text-gray-400 font-medium uppercase tracking-wide border-b border-gray-100 dark:border-gray-800">{{ t('tasks.selectAccount') }}</div>
            <button
              v-for="acc in runMenuAccounts" :key="acc"
              @click="doRun(task, acc)"
              class="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors truncate"
            >
              {{ acc }}
            </button>
          </div>
        </div>
        <button @click="openLogs(task)" class="flex-1 sm:flex-none flex justify-center items-center gap-1 px-2 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors text-xs" :title="t('tasks.viewLogs')">
          <FileText class="w-3.5 h-3.5" />
          <span class="text-xs">{{ t('tasks.logs') }}</span>
        </button>
        <button @click="openEdit(task)" class="flex-1 sm:flex-none flex justify-center items-center gap-1 px-2 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors text-xs" :title="t('tasks.edit')">
          <Edit2 class="w-3.5 h-3.5" />
          <span class="text-xs">{{ t('tasks.edit') }}</span>
        </button>
        <button @click="handleDelete(task)" class="flex-1 sm:flex-none flex justify-center items-center gap-1 px-2 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors text-xs" :title="t('tasks.delete')">
          <Trash2 class="w-3.5 h-3.5" />
          <span class="text-xs">{{ t('tasks.delete') }}</span>
        </button>
      </div>
    </div>
    </div>
    
    <div class="fixed bottom-6 right-6 lg:bottom-8 lg:right-8 z-40 flex flex-col items-end gap-2">
      <button 
        @click="showAddModal = true"
        class="w-11 h-11 flex items-center justify-center bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 border border-gray-800 dark:border-gray-200 shadow-md hover:shadow-lg hover:-translate-y-0.5 active:scale-95 transition-all duration-200"
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
