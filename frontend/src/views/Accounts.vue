<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, QrCode, Phone, Zap, MonitorSmartphone, MessageCircle, CheckCircle2, Search, RefreshCw, XCircle, X, Users } from 'lucide-vue-next'
import {
  deleteAccount,
  fetchAccountAvatar,
} from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAccountsStore } from '../stores/accounts'
import { useAccountBatchCheck } from '../composables/useAccountBatchCheck'
import type { AccountUiItem } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import AddAccountModal from '../components/accounts/AddAccountModal.vue'
import EditAccountModal from '../components/accounts/EditAccountModal.vue'
import DeviceManagerModal from '../components/accounts/DeviceManagerModal.vue'
import OfficialMessagesModal from '../components/accounts/OfficialMessagesModal.vue'
import PageRetry from '../components/PageRetry.vue'
import FilterEmptyState from '../components/FilterEmptyState.vue'
import { devLog } from '../lib/devLog'
import { AVATAR_FETCH_CONCURRENCY, mapPool } from '../lib/async-pool'
import { AvatarUrlCache } from '../lib/avatar-cache'
import {
  filterAccountsByQuery,
  mapAccountInfoToUiItem,
} from '../lib/account-list-map'

const router = useRouter()
const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const accountsStore = useAccountsStore()
const accounts = ref<AccountUiItem[]>([])
const pageLoading = ref(true)
// 会话内头像 URL 缓存：避免每次刷新重复请求与重复创建 ObjectURL
const avatarCache = new AvatarUrlCache()
// 卸载标记：在途头像请求完成后不再创建 ObjectURL，避免 blob 泄漏
let disposed = false
/** 重登弹窗延时句柄：卸载时清理，避免关闭组件后仍打开新弹窗 */
let reloginTimer: number | undefined
const showAddModal = ref(false)
const showEditModal = ref(false)
const showAddMenu = ref(false)
const initialMethod = ref<'code' | 'qr'>('code')
const initialAccountName = ref('')
const editingAccount = ref<AccountUiItem | null>(null)
const showDeviceModal = ref(false)
const deviceAccountName = ref('')
const showOfficialMessagesModal = ref(false)
const officialMessagesAccountName = ref('')
const searchQuery = ref('')
const loadError = ref(false)

const filteredAccounts = computed(() =>
  filterAccountsByQuery(accounts.value, searchQuery.value),
)

const hasListFilters = computed(() => searchQuery.value.trim().length > 0)

const clearListFilters = () => {
  searchQuery.value = ''
}

/** 账号管理页为单一事实来源：每次调用都强制刷新（增删改/检测后保持一致） */
const loadAccounts = async () => {
  const token = getAuthToken()
  if (!token) return

  try {
    loadError.value = false
    const list = await accountsStore.refreshAccounts()
    const labels = {
      loginExpired: t('accounts.loginExpired'),
      checking: t('accounts.checking'),
    }
    accounts.value = list.map((acc) => {
      const ui = mapAccountInfoToUiItem(acc, labels)
      // 复用已加载的头像 URL，未缓存项交由 loadAvatars 补充
      const cached = avatarCache.get(acc.name)
      if (cached) ui.avatarUrl = cached
      return ui
    })
    // 限流加载头像，避免账号多时并发打满连接
    void loadAvatars(accounts.value)
  } catch (e: unknown) {
    devLog.error('Failed to fetch accounts', e)
    loadError.value = true
    notifyApiError(e, 'accounts.loadFailed')
  } finally {
    pageLoading.value = false
  }
}

const loadAvatar = async (acc: AccountUiItem) => {
  const token = getAuthToken()
  try {
    let url = avatarCache.get(acc.name)
    if (!url) {
      const blob = await fetchAccountAvatar(token, acc.name)
      if (disposed) return // 组件已卸载：不再创建 ObjectURL，避免 blob 泄漏
      url = URL.createObjectURL(blob)
      avatarCache.set(acc.name, url)
    }
    acc.avatarUrl = url
  } catch {
    // 头像下载失败/无头像：保留首字母占位，不影响列表
    devLog.info('头像加载失败，保留占位:', acc.name)
  }
}

const loadAvatars = async (list: AccountUiItem[]) => {
  await mapPool(list, AVATAR_FETCH_CONCURRENCY, async (acc) => {
    await loadAvatar(acc)
  })
}

onMounted(async () => {
  await loadAccounts()
  // 刷新页面后恢复未完成的批量检测
  void resumeActiveBatchJob()
})

onUnmounted(() => {
  disposed = true
  if (reloginTimer !== undefined) {
    window.clearTimeout(reloginTimer)
    reloginTimer = undefined
  }
  // 离开页面时统一回收会话内头像 ObjectURL，避免 blob 泄漏
  avatarCache.release()
})

const handleDelete = async (name: string) => {
  const ok = await confirm({
    title: t('common.dangerConfirm'),
    message: t('accounts.deleteConfirm', { name }),
    confirmText: t('common.delete'),
    danger: true,
  })
  if (!ok) return
  const token = getAuthToken()
  try {
    await deleteAccount(token, name)
    toast.success(t('accounts.deleteSuccess'))
    await loadAccounts()
  } catch (e: unknown) {
    notifyApiError(e, 'accounts.deleteFailed')
  }
}

const {
  checkingAccount,
  batchChecking,
  batchJob,
  batchProgressPct,
  lastFailedAccountNames,
  handleCheck,
  handleBatchCheck,
  handleCancelBatchCheck,
  handleRecheckFailed,
  resumeActiveBatchJob,
} = useAccountBatchCheck({
  accounts,
  filteredAccounts,
  searchQuery,
  loadAccounts,
})

const openEdit = (acc: AccountUiItem) => {
  editingAccount.value = acc
  showEditModal.value = true
}

const openDevices = (name: string) => {
  deviceAccountName.value = name
  showDeviceModal.value = true
}

const openOfficialMessages = (name: string) => {
  officialMessagesAccountName.value = name
  showOfficialMessagesModal.value = true
}

const handleRelogin = (name: string) => {
  showEditModal.value = false
  reloginTimer = window.setTimeout(() => {
    initialAccountName.value = name
    initialMethod.value = 'code'
    showAddModal.value = true
  }, 300)
}

const openAddModal = (method: 'code' | 'qr') => {
  initialAccountName.value = ''
  initialMethod.value = method
  showAddMenu.value = false
  showAddModal.value = true
}

const goLogs = (name: string) => {
  router.push({ name: 'logs', query: { account: name } })
}

const goTasks = (name: string) => {
  router.push({ name: 'tasks', query: { account: name } })
}
</script>

<template>
  <div class="relative min-h-[80vh]">
    <!-- Page Loading skeleton -->
    <div v-if="pageLoading" class="space-y-4" aria-busy="true">
      <div class="ui-card p-3 flex justify-between">
        <div class="ui-skeleton h-4 w-24" />
        <div class="ui-skeleton h-8 w-28" />
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
        <div v-for="i in 4" :key="i" class="ui-card p-5 space-y-4">
          <div class="flex items-center gap-3">
            <div class="ui-skeleton w-10 h-10 shrink-0" />
            <div class="flex-1 space-y-2">
              <div class="ui-skeleton h-3.5 w-24" />
              <div class="ui-skeleton h-3 w-16" />
            </div>
          </div>
          <div class="ui-skeleton h-10 w-full" />
        </div>
      </div>
    </div>

    <!-- 加载失败（空列表时也要能重试，不能误显示 empty） -->
    <div v-else-if="loadError" class="space-y-4">
      <PageRetry
        :message="t('accounts.loadFailed')"
        :loading="pageLoading"
        @retry="pageLoading = true; loadAccounts()"
      />
    </div>

    <!-- Empty State -->
    <div v-else-if="accounts.length === 0" class="ui-empty">
      <div class="ui-empty-icon">
        <Users class="w-8 h-8" />
      </div>
      <p class="ui-empty-title">{{ t('accounts.empty') }}</p>
      <p class="ui-empty-desc mb-4">{{ t('accounts.emptyHint') }}</p>
      <div class="flex flex-wrap items-center justify-center gap-2">
        <button type="button" class="ui-btn-primary !text-xs !px-3 !py-2" @click="openAddModal('code')">
          <Phone class="w-3.5 h-3.5" /> {{ t('accounts.codeLogin') }}
        </button>
        <button type="button" class="ui-btn-secondary !text-xs !px-3 !py-2" @click="openAddModal('qr')">
          <QrCode class="w-3.5 h-3.5" /> {{ t('accounts.qrLogin') }}
        </button>
      </div>
    </div>

    <div v-else class="space-y-4 pb-20">
      <div class="ui-card flex flex-col sm:flex-row sm:items-center gap-3 p-3">
        <div class="text-xs text-gray-500 shrink-0">
          {{ t('accounts.total') }}：<span class="font-mono text-gray-800 dark:text-gray-200">{{ filteredAccounts.length }}</span>
          <span v-if="searchQuery.trim()" class="text-gray-400"> / {{ accounts.length }}</span>
        </div>
        <div class="relative flex-1 min-w-0 max-w-md">
          <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
          <input
            v-model="searchQuery"
            type="search"
            class="ui-input !pl-8 !h-9 !text-xs"
            :class="searchQuery.trim() ? '!pr-8' : ''"
            :placeholder="t('common.searchPlaceholder')"
            :aria-label="t('common.search')"
          >
          <button
            v-if="searchQuery.trim()"
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 rounded-sm"
            :title="t('common.clearFilters')"
            :aria-label="t('common.clearFilters')"
            @click="clearListFilters"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <div
            v-if="batchChecking && batchJob"
            class="flex flex-col items-end gap-0.5 min-w-0 sm:min-w-[7rem]"
          >
            <span class="text-[11px] font-mono text-sky-700 dark:text-sky-300 whitespace-nowrap">
              {{ t('accounts.batchCheckProgress', {
                done: batchJob.progress?.done ?? 0,
                total: batchJob.progress?.total ?? accounts.length,
              }) }}
              <template v-if="(batchJob.progress?.ok ?? 0) + (batchJob.progress?.fail ?? 0) > 0">
                · {{ t('accounts.batchCheckOkFail', {
                  ok: batchJob.progress?.ok ?? 0,
                  fail: batchJob.progress?.fail ?? 0,
                }) }}
              </template>
            </span>
            <div class="hidden sm:block w-full h-1 rounded-full bg-sky-100 dark:bg-sky-950/50 overflow-hidden">
              <div
                class="h-full bg-sky-500 transition-all duration-300"
                :style="{ width: `${batchProgressPct}%` }"
              />
            </div>
          </div>
          <button
            v-if="batchChecking && batchJob?.job_id"
            type="button"
            class="ui-btn-secondary !px-3 !py-2 !text-xs inline-flex items-center gap-1"
            @click="handleCancelBatchCheck"
          >
            <XCircle class="w-3.5 h-3.5" />
            {{ t('accounts.batchCheckCancel') }}
          </button>
          <button
            v-if="!batchChecking && lastFailedAccountNames.length > 0"
            type="button"
            class="ui-btn-secondary !px-3 !py-2 !text-xs inline-flex items-center gap-1"
            :title="t('accounts.batchRecheckFailedHint')"
            @click="handleRecheckFailed"
          >
            <RefreshCw class="w-3.5 h-3.5" />
            {{ t('accounts.batchRecheckFailed') }}
            <span class="font-mono opacity-80">({{ lastFailedAccountNames.length }})</span>
          </button>
          <button
            type="button"
            class="ui-btn-primary !px-3 !py-2 !text-xs inline-flex items-center gap-1"
            :disabled="batchChecking"
            :title="batchChecking ? t('accounts.batchChecking') : undefined"
            @click="handleBatchCheck"
          >
            <span v-if="batchChecking" class="ui-spinner !w-3.5 !h-3.5 !border-2" />
            <CheckCircle2 v-else class="w-3.5 h-3.5" />
            {{ batchChecking ? t('accounts.batchChecking') : t('accounts.batchCheck') }}
          </button>
        </div>
      </div>
      <div v-if="filteredAccounts.length === 0" class="ui-empty !py-12">
        <FilterEmptyState
          v-if="accounts.length > 0 && hasListFilters"
          :title="t('common.filterNoResults')"
          :hint="t('common.filterNoResultsHint')"
          :action-text="t('common.clearFilters')"
          @action="clearListFilters"
        />
        <p v-else class="ui-empty-desc">{{ t('common.noData') }}</p>
      </div>
      <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
    <div
      v-for="acc in filteredAccounts" :key="acc.id"
      class="ui-card ui-card-hover group relative flex flex-col p-5"
    >
      <div class="flex justify-between items-start mb-4">
        <div class="flex items-center gap-3 truncate max-w-[70%]">
          <div class="w-10 h-10 shrink-0 bg-gray-50 dark:bg-gray-950 flex items-center justify-center text-xs text-gray-500 font-mono border border-gray-200 dark:border-gray-800/40 overflow-hidden">
            <img 
              v-if="acc.avatarUrl" 
              :src="acc.avatarUrl" 
              :alt="acc.name"
              class="w-full h-full object-cover"
            />
            <span v-else>{{ acc.name.substring(0, 2) }}</span>
          </div>
          <div class="truncate">
            <div class="text-sm font-medium text-gray-900 dark:text-gray-200 truncate" :title="acc.name">{{ acc.name }}</div>
            <div class="text-xs text-gray-500 mt-0.5 font-mono truncate" :title="acc.remark || t('accounts.noRemark')">{{ acc.remark || t('accounts.noRemark') }}</div>
          </div>
        </div>
        
        <!-- Status Indicator -->
        <div class="flex items-center gap-2 shrink-0 max-w-[45%]">
          <span
            class="ui-badge max-w-full"
            :class="{
              'ui-badge-success': acc.status === 'active',
              'ui-badge-warn': acc.status === 'empty',
              'ui-badge-error': acc.status === 'error',
            }"
            :title="acc.message || (acc.status === 'active' ? t('accounts.statusOk') : '')"
          >
            <span class="ui-badge-dot" />
            <span class="truncate">
              {{ acc.status === 'active' ? t('accounts.statusOk') : (acc.message || t('accounts.statusUnknown')) }}
            </span>
          </span>
        </div>
      </div>

      <!-- Actions：竖排布局保留，语义走 ui-row-action -->
      <div class="mt-auto pt-3 border-t border-gray-100 dark:border-gray-800/40 grid grid-cols-7 gap-0.5">
        <button type="button" class="ui-row-action ui-row-action--stack" :disabled="checkingAccount === acc.name" :title="t('accounts.checkStatus')" @click="handleCheck(acc.name)">
          <span v-if="checkingAccount === acc.name" class="ui-spinner !w-3.5 !h-3.5 !border-2" />
          <Play v-else class="w-3.5 h-3.5" />
          <span>{{ t('accounts.check') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack" :title="t('accounts.viewTasks')" @click="goTasks(acc.name)">
          <Zap class="w-3.5 h-3.5" />
          <span>{{ t('accounts.tasks') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack" :title="t('accounts.viewLogs')" @click="goLogs(acc.name)">
          <FileText class="w-3.5 h-3.5" />
          <span>{{ t('accounts.logs') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack" :title="t('accounts.devices')" @click="openDevices(acc.name)">
          <MonitorSmartphone class="w-3.5 h-3.5" />
          <span>{{ t('accounts.devicesShort') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack" :title="t('accounts.officialMessages')" @click="openOfficialMessages(acc.name)">
          <MessageCircle class="w-3.5 h-3.5" />
          <span>{{ t('accounts.officialMessagesShort') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack" :title="t('accounts.edit')" @click="openEdit(acc)">
          <Edit2 class="w-3.5 h-3.5" />
          <span>{{ t('accounts.editBtn') }}</span>
        </button>
        <button type="button" class="ui-row-action ui-row-action--stack ui-row-action--danger" :title="t('accounts.deleteBtn')" @click="handleDelete(acc.name)">
          <Trash2 class="w-3.5 h-3.5" />
          <span>{{ t('accounts.deleteBtn') }}</span>
        </button>
      </div>
    </div>
    </div>
    </div>

    <!-- FAB for Adding Account -->
    <div class="fixed ui-safe-fab z-40 flex flex-col items-end gap-2">
      <transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0 translate-y-2" enter-to-class="opacity-100 translate-y-0" leave-active-class="transition duration-150 ease-in" leave-from-class="opacity-100 translate-y-0" leave-to-class="opacity-0 translate-y-2">
        <div v-if="showAddMenu" class="flex flex-col gap-1.5 mb-1">
          <button type="button" class="ui-card ui-card-hover flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 shadow-[var(--sp-shadow-md)]" @click="openAddModal('qr')">
            <QrCode class="w-4 h-4 text-gray-500" /> {{ t('accounts.qrLogin') }}
          </button>
          <button type="button" class="ui-card ui-card-hover flex items-center gap-2.5 px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 shadow-[var(--sp-shadow-md)]" @click="openAddModal('code')">
            <Phone class="w-4 h-4 text-gray-500" /> {{ t('accounts.codeLogin') }}
          </button>
        </div>
      </transition>
      
      <button 
        type="button"
        class="ui-fab"
        :aria-expanded="showAddMenu"
        :aria-label="showAddMenu ? t('common.close') : t('accounts.addAccount')"
        :title="showAddMenu ? t('common.close') : t('accounts.addAccount')"
        @click="showAddMenu = !showAddMenu"
      >
        <Plus class="w-5 h-5 transition-transform duration-200" :class="{ 'rotate-45': showAddMenu }" />
      </button>
    </div>

    <!-- Modals -->
    <AddAccountModal :isOpen="showAddModal" :initialMethod="initialMethod" :initialAccountName="initialAccountName" @close="showAddModal = false" @success="loadAccounts" />
    <EditAccountModal v-if="editingAccount" :isOpen="showEditModal" :account="editingAccount" @close="showEditModal = false" @success="loadAccounts" @relogin="handleRelogin" />
    <DeviceManagerModal :isOpen="showDeviceModal" :accountName="deviceAccountName" @close="showDeviceModal = false" />
    <OfficialMessagesModal :isOpen="showOfficialMessagesModal" :accountName="officialMessagesAccountName" @close="showOfficialMessagesModal = false" />
  </div>
</template>
