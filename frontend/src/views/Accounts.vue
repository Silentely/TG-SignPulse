<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Play, FileText, Edit2, Trash2, Plus, QrCode, Phone, Zap, MonitorSmartphone, MessageCircle, CheckCircle2, Search } from 'lucide-vue-next'
import { listAccounts, deleteAccount, checkAccountsStatus } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useAuthStore } from '../stores/auth'
import type { AccountUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import AddAccountModal from '../components/accounts/AddAccountModal.vue'
import EditAccountModal from '../components/accounts/EditAccountModal.vue'
import DeviceManagerModal from '../components/accounts/DeviceManagerModal.vue'
import OfficialMessagesModal from '../components/accounts/OfficialMessagesModal.vue'
import PageRetry from '../components/PageRetry.vue'
import { devLog } from '../lib/devLog'

const router = useRouter()
const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()
const accounts = ref<AccountUiItem[]>([])
const pageLoading = ref(true)
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

const filteredAccounts = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return accounts.value
  return accounts.value.filter(
    (a) =>
      a.name.toLowerCase().includes(q) ||
      (a.remark || '').toLowerCase().includes(q) ||
      (a.message || '').toLowerCase().includes(q)
  )
})

const loadAccounts = async () => {
  const token = authStore.token || ''
  if (!token) return

  try {
    loadError.value = false
    const res = await listAccounts(token)
    accounts.value = res.accounts.map(acc => {
      let uiStatus = 'active'
      let message = ''

      if (acc.needs_relogin || acc.status === 'invalid') {
        uiStatus = 'error'
        message = t('accounts.loginExpired')
      } else if (acc.status === 'error') {
        uiStatus = 'error'
        message = acc.status_message || ''
      } else if (acc.status === 'checking') {
        uiStatus = 'empty'
        message = t('accounts.checking')
      } else if (acc.status_message?.includes('流量') || acc.status_message?.includes('额度')) {
        uiStatus = 'empty'
        message = acc.status_message
      }

      return {
        id: acc.name,
        name: acc.name,
        remark: acc.remark,
        status: uiStatus,
        message: message,
        avatarUrl: '',
        avatarLoaded: false,
        raw: acc
      }
    })
    // Load avatars with auth token
    for (const acc of accounts.value) {
      loadAvatar(acc)
    }
  } catch (e) {
    devLog.error('Failed to fetch accounts', e)
    loadError.value = true
    toast.error(getLocalizedErrorMessage(e, t, t('accounts.loadFailed')))
  } finally {
    pageLoading.value = false
  }
}

const loadAvatar = async (acc: AccountUiItem) => {
  const token = authStore.token || ''
  try {
    const res = await fetch(`/api/accounts/${encodeURIComponent(acc.name)}/avatar`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    if (res.ok) {
      const blob = await res.blob()
      acc.avatarUrl = URL.createObjectURL(blob)
    }
  } catch {
    // No avatar available, keep fallback
  }
  acc.avatarLoaded = true
}

onMounted(() => {
  loadAccounts()
})

const handleDelete = async (name: string) => {
  const ok = await confirm({
    title: t('common.dangerConfirm'),
    message: `${t('accounts.deleteConfirm')} ${name} ?`,
    confirmText: t('common.delete'),
    danger: true,
  })
  if (!ok) return
  const token = authStore.token || ''
  try {
    await deleteAccount(token, name)
    toast.success(t('accounts.deleteSuccess'))
    await loadAccounts()
  } catch (e) {
    toast.error(getLocalizedErrorMessage(e, t, t('accounts.deleteFailed')))
  }
}

const checkingAccount = ref('')
const batchChecking = ref(false)

const handleCheck = async (name: string) => {
  const token = authStore.token || ''
  checkingAccount.value = name
  try {
    const res = await checkAccountsStatus(token, { account_names: [name] })
    await loadAccounts()
    // Show result
    const result = res.results?.[0]
    if (result) {
      if (result.ok) {
        toast.success(`${name}: ${t('accounts.checkOk')}`)
      } else {
        toast.error(`${name}: ${result.message || t('accounts.loginExpired')}`)
      }
    }
  } catch (e) {
    toast.error(getLocalizedErrorMessage(e, t, t('accounts.checkFailed')))
  } finally {
    checkingAccount.value = ''
  }
}

const handleBatchCheck = async () => {
  const token = authStore.token || ''
  const names = accounts.value.map(acc => acc.name).filter(Boolean)
  if (!token || names.length === 0) return

  batchChecking.value = true
  try {
    const res = await checkAccountsStatus(token, { account_names: names, timeout_seconds: 8 })
    await loadAccounts()
    const ok = res.results.filter(item => item.ok).length
    const failed = res.results.length - ok
    if (failed === 0) {
      toast.success(t('accounts.batchCheckDone'), {
        description: `${t('accounts.checkOkCount')}: ${ok}`,
      })
    } else {
      const failedPreview = res.results
        .filter(item => !item.ok)
        .slice(0, 5)
        .map(item => `${item.account_name}: ${item.message || item.code || t('accounts.loginExpired')}`)
        .join('\n')
      toast.error(t('accounts.batchCheckDone'), {
        description: `${t('accounts.checkOkCount')}: ${ok} · ${t('accounts.checkFailedCount')}: ${failed}\n${failedPreview}`,
        duration: 8000,
      })
    }
  } catch (e) {
    toast.error(getLocalizedErrorMessage(e, t, t('accounts.checkFailed')))
  } finally {
    batchChecking.value = false
  }
}

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
  setTimeout(() => {
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
        <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
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
            :placeholder="t('common.searchPlaceholder')"
            :aria-label="t('common.search')"
          >
        </div>
        <button
          type="button"
          class="ui-btn-primary !px-3 !py-2 !text-xs shrink-0"
          :disabled="batchChecking"
          @click="handleBatchCheck"
        >
          <span v-if="batchChecking" class="ui-spinner !w-3.5 !h-3.5 !border-2" />
          <CheckCircle2 v-else class="w-3.5 h-3.5" />
          {{ batchChecking ? t('accounts.batchChecking') : t('accounts.batchCheck') }}
        </button>
      </div>
      <div v-if="filteredAccounts.length === 0" class="ui-empty !py-12">
        <p class="ui-empty-desc">{{ t('common.noData') }}</p>
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

      <!-- Actions -->
      <div class="mt-auto pt-3 border-t border-gray-100 dark:border-gray-800/40 grid grid-cols-7 gap-0.5">
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors disabled:opacity-50" :disabled="checkingAccount === acc.name" :title="t('accounts.checkStatus')" @click="handleCheck(acc.name)">
          <span v-if="checkingAccount === acc.name" class="ui-spinner !w-3.5 !h-3.5 !border-2" />
          <Play v-else class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.check') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors" :title="t('accounts.viewTasks')" @click="goTasks(acc.name)">
          <Zap class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.tasks') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors" :title="t('accounts.viewLogs')" @click="goLogs(acc.name)">
          <FileText class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.logs') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors" :title="t('accounts.devices')" @click="openDevices(acc.name)">
          <MonitorSmartphone class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.devicesShort') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors" :title="t('accounts.officialMessages')" @click="openOfficialMessages(acc.name)">
          <MessageCircle class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.officialMessagesShort') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm transition-colors" :title="t('accounts.edit')" @click="openEdit(acc)">
          <Edit2 class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.editBtn') }}</span>
        </button>
        <button type="button" class="flex flex-col items-center gap-0.5 py-1.5 text-gray-500 hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/10 rounded-sm transition-colors" :title="t('accounts.deleteBtn')" @click="handleDelete(acc.name)">
          <Trash2 class="w-3.5 h-3.5" />
          <span class="text-[10px]">{{ t('accounts.deleteBtn') }}</span>
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
        :aria-label="showAddMenu ? t('common.close') : t('accounts.empty')"
        :title="showAddMenu ? t('common.close') : t('accounts.codeLogin')"
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
