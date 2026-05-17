<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, Radio, Clock, Shuffle } from 'lucide-vue-next'
import { listSignTasks, deleteSignTask, startSignTaskRun, listAccounts } from '../lib/api' 
import { useI18n } from '../composables/useI18n'
import AddTaskModal from '../components/tasks/AddTaskModal.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'
import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'

const route = useRoute()
const { t } = useI18n()
const tasks = ref<any[]>([])
const pageLoading = ref(true)
const showAddModal = ref(false)
const showEditModal = ref(false)
const showLogsModal = ref(false)
const editingTask = ref<any>(null)
const logsTask = ref<any>(null)

// Account selection for run
const runMenuTask = ref<any>(null)
const runMenuAccounts = ref<string[]>([])
const allAccounts = ref<string[]>([])

const loadAllAccounts = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return
  try {
    const res = await listAccounts(token)
    allAccounts.value = (res.accounts || []).map((a: any) => a.name)
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

const getTaskAccountName = (task: any): string => {
  // Resolve a usable account name from task data, skipping wildcard '*'
  const name = task.account_name || ''
  if (name && name !== '*') return name
  const names = task.account_names || []
  for (const n of names) {
    if (n && n !== '*') return n
  }
  return ''
}

const loadTasks = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  pageLoading.value = true
  try {
    const accountName = route.query.account as string | undefined
    const res = await listSignTasks(token, accountName)
    tasks.value = res.map((task: any) => {
      const firstChat = task.chats && task.chats.length > 0 ? task.chats[0] : null
      const targetStr = firstChat ? `${firstChat.chat_id}${firstChat.message_thread_id ? '|' + firstChat.message_thread_id : ''}` : t('tasks.noTarget')
      
      let scheduleMode = ''
      let modeIcon: any = Clock
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
        lastRunStr = t('tasks.continuousRunning')
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
        chatAvatarUrl: '',
        chatName: firstChat ? (firstChat.name || `Chat ${firstChat.chat_id}`) : '',
        raw: task
      }
    })

    // Load chat avatars using resolved account name
    for (const task of tasks.value) {
      const firstChat = task.raw.chats?.[0]
      const avatarAccount = getTaskAccountName(task.raw)
      if (firstChat && avatarAccount) {
        loadChatAvatar(task, avatarAccount, firstChat.chat_id)
      }
    }
  } catch (e) {
    console.error('Failed to fetch tasks', e)
  } finally {
    pageLoading.value = false
  }
}

onMounted(() => {
  loadTasks()
  loadAllAccounts()
})

const loadChatAvatar = async (task: any, accountName: string, chatId: number) => {
  const token = localStorage.getItem('tg-signer-token') || ''
  const cacheKey = `avatar_${accountName}_${chatId}`
  
  // Check sessionStorage cache first
  const cached = sessionStorage.getItem(cacheKey)
  if (cached) {
    task.chatAvatarUrl = cached
    return
  }

  try {
    const res = await fetch(`/api/sign-tasks/chats/${encodeURIComponent(accountName)}/avatar/${chatId}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (res.ok) {
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      task.chatAvatarUrl = url
      // Cache as data URL for persistence across page navigations
      try {
        const reader = new FileReader()
        reader.onload = () => {
          if (reader.result) sessionStorage.setItem(cacheKey, reader.result as string)
        }
        reader.readAsDataURL(blob)
      } catch {}
    }
  } catch {
    // No avatar, keep fallback
  }
}

watch(() => route.query.account, () => {
  loadTasks()
})

const handleDelete = async (task: any) => {
  if (!confirm(`${t('tasks.deleteConfirm')} ${task.name} ?`)) return
  const token = localStorage.getItem('tg-signer-token') || ''
  try {
    const accountName = getTaskAccountName(task.raw) || undefined
    await deleteSignTask(token, task.name, accountName)
    await loadTasks()
  } catch (e: any) {
    alert(`${t('tasks.deleteFailed')}: ${e.message || t('tasks.unknownError')}`)
  }
}

const getTaskRealAccounts = (task: any): string[] => {
  const names = task.account_names || []
  if (names.includes('*')) {
    // Wildcard: expand to all accounts
    return allAccounts.value.length > 0 ? allAccounts.value : []
  }
  return names.filter((n: string) => n && n !== '*')
}

const handleRun = (task: any) => {
  const accounts = getTaskRealAccounts(task.raw)
  if (accounts.length <= 1) {
    // Single account or no accounts - run directly
    doRun(task, accounts[0] || getTaskAccountName(task.raw))
  } else {
    // Multiple accounts - show selection menu
    runMenuTask.value = task
    runMenuAccounts.value = accounts
  }
}

const doRun = async (task: any, accountName: string) => {
  runMenuTask.value = null
  const token = localStorage.getItem('tg-signer-token') || ''
  try {
    await startSignTaskRun(token, task.name, accountName)
    // Open logs modal to show real-time execution
    logsTask.value = task
    showLogsModal.value = true
  } catch(e: any) {
    alert(`${t('tasks.triggerFailed')}: ${e.message}`)
  }
}

const closeRunMenu = () => {
  runMenuTask.value = null
}

const openEdit = (task: any) => {
  editingTask.value = task.raw
  showEditModal.value = true
}

const openLogs = (task: any) => {
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
    <div 
      v-for="task in tasks" :key="task.id"
      class="group flex flex-col sm:flex-row sm:items-center p-4 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 hover:border-gray-300 dark:hover:border-gray-700 transition-colors"
    >
      <!-- Mobile Layout: Avatar + Name + Status -->
      <div class="flex-1 flex gap-3 w-full overflow-hidden">
        
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
    <EditTaskModal :isOpen="showEditModal" :task="editingTask" @close="showEditModal = false" @success="loadTasks" />
    <TaskLogsModal :isOpen="showLogsModal" :task="logsTask" @close="showLogsModal = false" />
  </div>
</template>
