<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { listAccounts, listSignTasks, getRecentAccountLogs } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import Modal from '../components/Modal.vue'

const { t } = useI18n()

let refreshTimer: ReturnType<typeof setInterval> | null = null
const selectedLog = ref<any>(null)

const stats = ref([
  { key: 'dashboard.activeAccounts', value: '...' },
  { key: 'dashboard.totalTasks', value: '...' },
  { key: 'dashboard.recentSuccess', value: '...' },
  { key: 'dashboard.recentFailure', value: '...' },
])

const logs = ref<any[]>([])

const formatTime = (isoString: string) => {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString('en-US', { hour12: false })
}

onMounted(async () => {
  await loadDashboardData()
  refreshTimer = setInterval(loadDashboardData, 30000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

const loadDashboardData = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

    let accRes: { accounts: any[]; total: number } = { accounts: [], total: 0 }
    let tasksRes: any[] = []
    let logsRes: any[] = []

    try { accRes = await listAccounts(token) } catch (e) { console.error('Failed to load accounts', e) }
    try { tasksRes = await listSignTasks(token) } catch (e) { console.error('Failed to load tasks', e) }
    try { logsRes = await getRecentAccountLogs(token, 20) } catch (e) { console.error('Failed to load logs', e) }

    const activeAccs = accRes.accounts ? accRes.accounts.filter((a: any) => a.status === 'connected' || a.status === 'checking').length : 0
    
    const today = new Date().toISOString().split('T')[0]
    let todaySuccess = 0
    let todayFail = 0
    
    if (Array.isArray(logsRes)) {
      logsRes.forEach((l: any) => {
        if (l.created_at.startsWith(today)) {
          if (l.success) todaySuccess++
          else todayFail++
        }
      })
    }

    stats.value = [
      { key: 'dashboard.activeAccounts', value: `${activeAccs}/${accRes.total || 0}` },
      { key: 'dashboard.totalTasks', value: `${Array.isArray(tasksRes) ? tasksRes.length : 0}` },
      { key: 'dashboard.recentSuccess', value: `${todaySuccess}` },
      { key: 'dashboard.recentFailure', value: `${todayFail}` },
    ]

    if (Array.isArray(logsRes)) {
      logs.value = logsRes.map((l: any) => ({
        time: formatTime(l.created_at),
        account: l.account_name,
        task: l.task_name,
        status: l.success ? 'success' : 'error',
        text: l.message
      }))
    }
}
</script>

<template>
  <div class="space-y-8">
    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div 
        v-for="stat in stats" 
        :key="stat.key"
        class="p-5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 flex flex-col justify-between"
      >
        <span class="text-xs text-gray-500 font-medium tracking-wide">{{ t(stat.key) }}</span>
        <span class="text-2xl font-mono text-gray-900 dark:text-gray-100 mt-2">{{ stat.value }}</span>
      </div>
    </div>

    <!-- Terminal Logs -->
    <div class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-5 min-h-[400px]">
      <div class="text-xs text-gray-500 font-medium tracking-wide mb-4">{{ t('dashboard.recentLogs') }}</div>
      <div class="font-mono text-xs overflow-x-auto">
        <div v-for="(log, idx) in logs" :key="idx" 
          @click="selectedLog = log"
          class="flex items-center gap-4 hover:bg-gray-50 dark:hover:bg-gray-800/30 px-2 py-1.5 transition-colors cursor-pointer whitespace-nowrap min-w-max">
          <span class="text-gray-500 dark:text-gray-600 shrink-0">{{ log.time }}</span>
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

    <!-- Log Detail Modal -->
    <Modal :isOpen="!!selectedLog" @close="selectedLog = null" :title="t('logs.detailTitle')">
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
        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div class="text-xs text-gray-500 mb-1">{{ t('logs.execInfo') }}</div>
          <div class="p-2 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs font-mono whitespace-pre-wrap break-all max-h-60 overflow-y-auto text-gray-800 dark:text-gray-300">{{ selectedLog.text || t('logs.noDetail') }}</div>
        </div>
      </div>
    </Modal>
  </div>
</template>
