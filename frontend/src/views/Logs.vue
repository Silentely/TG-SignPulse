<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute } from 'vue-router'
import { getTaskHistoryLogs, getTaskHistoryLogDetail, getLoginAuditLogs, listAccounts } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import Modal from '../components/Modal.vue'
import CustomSelect from '../components/CustomSelect.vue'
import DatePicker from '../components/DatePicker.vue'

const { locale, t } = useI18n()
const route = useRoute()

const activeTab = ref<'tasks' | 'login'>('tasks')

const filterTask = ref('')
const filterAccount = ref('')
const filterDate = ref('')
const filterStatus = ref<'' | 'success' | 'error'>('')

const logs = ref<any[]>([])
const accountsList = ref<string[]>([])
const selectedLog = ref<any>(null)
const logDetail = ref<any>(null)
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

const loadAccounts = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return
  try {
    const res = await listAccounts(token)
    accountsList.value = res.accounts.map((a: any) => a.name)
  } catch (e) {
    console.error('Failed to load accounts for filter', e)
  }
}

const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  const loc = locale.value === 'zh' ? 'zh-CN' : 'en-US'
  return d.toLocaleString(loc, { hour12: false })
}

const loadTaskLogs = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  try {
    const res = await getTaskHistoryLogs(token, {
      limit: 100,
      account_name: filterAccount.value || undefined,
      date: filterDate.value || undefined
    })

    let filtered = res
    if (filterTask.value) {
      filtered = filtered.filter((l: any) => l.task_name.includes(filterTask.value))
    }
    if (filterStatus.value) {
      filtered = filtered.filter((l: any) => 
        filterStatus.value === 'success' ? l.success : !l.success
      )
    }

    logs.value = filtered.map((l: any) => ({
      id: l.id,
      time: formatTime(l.created_at),
      created_at: l.created_at,
      account: l.account_name,
      task: l.task_name,
      status: l.success ? 'success' : 'error',
      text: l.summary || l.message,
      flow_line_count: l.flow_line_count || 0
    }))
  } catch (e) {
    console.error('Failed to fetch logs', e)
  }
}

const loginLogs = ref<any[]>([])
const loadLoginLogs = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  try {
    const res = await getLoginAuditLogs(token, {
      limit: 100,
      date: filterDate.value || undefined
    })

    loginLogs.value = res.map((l: any) => ({
      id: l.id,
      time: formatTime(l.created_at),
      username: l.username,
      ip: l.ip_address || '-',
      status: l.success ? 'success' : 'error',
      text: l.detail || (l.success ? t('logs.loginSuccess') : t('logs.loginFailed'))
    }))
  } catch (e) {
    console.error('Failed to fetch login logs', e)
  }
}

const loadLogs = () => {
  if (activeTab.value === 'tasks') {
    loadTaskLogs()
  } else {
    loadLoginLogs()
  }
}

const openLogDetail = async (log: any) => {
  selectedLog.value = log
  logDetail.value = null

  // Fetch full detail with flow_logs
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token || !log.account || !log.task || !log.created_at) return

  detailLoading.value = true
  try {
    const detail = await getTaskHistoryLogDetail(token, {
      account_name: log.account,
      task_name: log.task,
      created_at: log.created_at
    })
    logDetail.value = detail
  } catch (e) {
    console.error('Failed to fetch log detail', e)
  } finally {
    detailLoading.value = false
  }
}

watch(activeTab, () => {
  loadLogs()
})

watch([filterTask, filterAccount, filterDate, filterStatus], () => {
  loadLogs()
})

onMounted(() => {
  const queryAccount = route.query.account as string | undefined
  if (queryAccount) {
    filterAccount.value = queryAccount
  }
  loadAccounts()
  loadLogs()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tabs -->
    <div class="flex gap-6 mb-4 border-b border-gray-200 dark:border-gray-800">
      <button 
        @click="activeTab = 'tasks'"
        class="pb-2 text-sm font-medium transition-colors border-b-2"
        :class="activeTab === 'tasks' ? 'border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
      >
        {{ t('logs.taskLogs') }}
      </button>
      <button 
        @click="activeTab = 'login'"
        class="pb-2 text-sm font-medium transition-colors border-b-2"
        :class="activeTab === 'login' ? 'border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
      >
        {{ t('logs.auditLogs') }}
      </button>
    </div>

    <!-- Filters -->
    <div v-if="activeTab === 'tasks'" class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
      <input 
        v-model="filterTask"
        type="text" 
        :placeholder="t('logs.taskName')"
        class="bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-gray-200 px-3 py-2 outline-none border border-gray-200 dark:border-gray-800/60 focus:border-gray-400 dark:focus:border-gray-600 transition-colors w-full placeholder:text-gray-400 dark:placeholder:text-gray-600"
      >
      <CustomSelect v-model="filterAccount" :options="accountOptions" />
      <CustomSelect v-model="filterStatus" :options="statusOptions" />
      <DatePicker v-model="filterDate" />
    </div>

    <!-- Logs List -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-3 sm:p-5 flex-1 min-h-[500px] overflow-y-auto">
      <div v-if="activeTab === 'tasks'" class="font-mono text-xs space-y-0">
        <!-- Empty state -->
        <div v-if="logs.length === 0" class="flex flex-col items-center justify-center py-16 text-center font-sans">
          <p class="text-sm text-gray-500">{{ t('logs.empty') }}</p>
          <p class="text-xs text-gray-400 mt-1">{{ t('logs.emptyHint') }}</p>
        </div>
        <div class="overflow-x-auto">
          <div v-for="log in logs" :key="log.id" 
            @click="openLogDetail(log)"
            class="flex items-center gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/30 px-2 py-1.5 transition-colors cursor-pointer whitespace-nowrap min-w-max">
            <span class="text-gray-500 dark:text-gray-600 shrink-0 w-[140px]">{{ log.time }}</span>
            <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate">{{ log.account }}</span>
            <span class="text-gray-600 dark:text-gray-500 shrink-0 w-28 truncate">{{ log.task }}</span>
            <div class="shrink-0 w-4 flex items-center justify-center">
              <div v-if="log.status === 'success'" class="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
              <div v-else-if="log.status === 'error'" class="w-1.5 h-1.5 rounded-full bg-rose-500"></div>
            </div>
            <span 
              class="truncate max-w-[300px]"
              :class="{
                'text-gray-800 dark:text-gray-300': log.status === 'success',
                'text-rose-600 dark:text-rose-400/90': log.status === 'error',
              }"
            >
              {{ log.text }}
            </span>
          </div>
        </div>
      </div>
      
      <div v-else class="font-mono text-xs space-y-2">
        <div v-for="log in loginLogs" :key="log.id" class="flex items-start gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/30 px-2 py-1.5 -mx-2 transition-colors">
          <span class="text-gray-500 dark:text-gray-600 shrink-0">{{ log.time }}</span>
          <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate">{{ log.username }}</span>
          <span class="text-gray-500 dark:text-gray-500 shrink-0 w-32 truncate">{{ log.ip }}</span>
          
          <div class="shrink-0 w-4 flex items-center justify-center mt-0.5">
            <div v-if="log.status === 'success'" class="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
            <div v-else class="w-1.5 h-1.5 rounded-full bg-rose-500"></div>
          </div>

          <span 
            class="truncate"
            :class="{
              'text-gray-800 dark:text-gray-300': log.status === 'success',
              'text-rose-600 dark:text-rose-400/90': log.status === 'error'
            }"
          >
            {{ log.text }}
          </span>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <Modal :isOpen="!!selectedLog" @close="selectedLog = null; logDetail = null" :title="t('logs.detailTitle')">
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="flex items-center gap-3">
          <div class="w-2 h-2 rounded-full" :class="selectedLog.status === 'success' ? 'bg-emerald-500' : 'bg-rose-500'"></div>
          <span class="font-medium text-gray-900 dark:text-gray-100">{{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}</span>
        </div>
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div><span class="text-gray-500">{{ t('logs.time') }}</span><span class="text-gray-900 dark:text-gray-200">{{ selectedLog.time }}</span></div>
          <div><span class="text-gray-500">{{ t('logs.account') }}</span><span class="text-gray-900 dark:text-gray-200">{{ selectedLog.account }}</span></div>
          <div class="col-span-2"><span class="text-gray-500">{{ t('logs.task') }}</span><span class="text-gray-900 dark:text-gray-200">{{ selectedLog.task }}</span></div>
        </div>

        <!-- Detailed log content -->
        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <!-- Loading state -->
          <div v-if="detailLoading" class="flex items-center gap-2 text-xs text-gray-500 py-4 justify-center">
            <svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            {{ t('common.loading') }}
          </div>

          <!-- Last target message -->
          <div v-if="logDetail?.last_target_message" class="mb-3">
            <div class="text-xs text-gray-500 mb-1 font-semibold">{{ t('taskLogs.lastResponse') }}</div>
            <div class="p-2 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs whitespace-pre-wrap break-all max-h-40 overflow-y-auto text-gray-800 dark:text-gray-300">{{ logDetail.last_target_message }}</div>
          </div>

          <!-- Flow logs (detailed execution log) -->
          <div v-if="logDetail?.flow_logs && logDetail.flow_logs.length > 0" class="mb-3">
            <div class="text-xs text-gray-500 mb-1 font-semibold">{{ t('taskLogs.logDetail') }}</div>
            <div class="p-2 bg-gray-900 text-gray-300 border border-gray-700 text-xs font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto">
              <div v-for="(line, i) in logDetail.flow_logs" :key="i">{{ line }}</div>
              <div v-if="logDetail.flow_truncated" class="text-gray-500 italic mt-1">{{ t('taskLogs.truncated') }}</div>
            </div>
          </div>

          <!-- Summary / fallback message -->
          <div v-else-if="!detailLoading">
            <div class="text-xs text-gray-500 mb-1">{{ t('logs.execInfo') }}</div>
            <div class="p-2 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto text-gray-800 dark:text-gray-300">{{ logDetail?.message || selectedLog.text || t('logs.noDetail') }}</div>
          </div>
        </div>
      </div>
    </Modal>
  </div>
</template>
