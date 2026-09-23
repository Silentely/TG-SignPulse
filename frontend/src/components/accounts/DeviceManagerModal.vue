<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { Check, Copy, Download, LogOut, RefreshCw, ShieldCheck, Trash2 } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import {
  listAccountDevices,
  listAccountOfficialMessages,
  exportStandaloneSession,
  resetOtherDevices,
  terminateAccountDevice,
  type AccountDeviceInfo,
  type OfficialMessageInfo,
} from '../../lib/api'
import { getAuthToken } from '../../lib/api/core'
import { useI18n } from '../../composables/useI18n'
import { useConfirm } from '../../composables/useConfirm'
import { formatDateTime } from '../../lib/datetime'
import { copyToClipboard } from '../../lib/clipboard'
import { getLocalizedErrorMessage } from '../../lib/types'
import { useLatestResponseGuard } from '../../lib/latest-response'

const props = defineProps<{
  isOpen: boolean
  accountName: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'reset-others'): void
}>()

const { t } = useI18n()
const { confirm } = useConfirm()
// 关闭弹窗或切换账号后，仍在途的响应不得回写列表
const devicesGuard = useLatestResponseGuard()
const officialGuard = useLatestResponseGuard()
// 「已复制」恢复定时器句柄：卸载时必须清理，避免回调写已销毁组件
let copyResetTimer: ReturnType<typeof setTimeout> | null = null
const devices = ref<AccountDeviceInfo[]>([])
const officialMessages = ref<OfficialMessageInfo[]>([])
const loading = ref(false)
const officialLoading = ref(false)
const resettingOthers = ref(false)
const error = ref('')
const successMessage = ref('')
const terminatingHash = ref('')

const exportingSession = ref(false)
const exportedModalOpen = ref(false)
const exportedSessionString = ref("")
const exportedDcId = ref<number | null>(null)
const exportedUserId = ref<number | null>(null)
const copied = ref(false)

const handleExportSession = async () => {
  const ok = await confirm({
    title: t("accounts.exportStandaloneSessionConfirmTitle"),
    message: t("accounts.exportStandaloneSessionConfirm"),
    confirmText: t("accounts.exportStandaloneSessionShort"),
  })
  if (!ok) return

  const token = getAuthToken()
  if (!token || !props.accountName) return

  exportingSession.value = true
  error.value = ""
  successMessage.value = ""
  try {
    const res = await exportStandaloneSession(token, props.accountName)
    exportedSessionString.value = res.session_string || ""
    exportedDcId.value = res.dc_id ?? null
    exportedUserId.value = res.user_id ?? null
    exportedModalOpen.value = true
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t("accounts.exportStandaloneSessionFailed"))
  } finally {
    exportingSession.value = false
  }
}

const copySessionString = async () => {
  if (!exportedSessionString.value) return
  if (copyResetTimer !== null) clearTimeout(copyResetTimer)
  copied.value = await copyToClipboard(exportedSessionString.value)
  if (copied.value) {
    copyResetTimer = setTimeout(() => {
      copied.value = false
      copyResetTimer = null
    }, 2000)
  }
}

const downloadSessionFile = () => {
  if (!exportedSessionString.value) return
  const blob = new Blob([exportedSessionString.value], { type: "text/plain;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = `${props.accountName}.session.txt`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

const title = computed(() => {
  const name = props.accountName?.trim()
  return name ? `${t('accounts.devicesTitle')} - ${name}` : t('accounts.devicesTitle')
})

const toTimestamp = (val?: string | number | null): number => {
  if (!val) return 0
  if (typeof val === 'number') return val
  const parsed = new Date(val).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

const sortedDevices = computed(() => {
  const list = [...devices.value]
  list.sort((a, b) => {
    if (a.current && !b.current) return -1
    if (!a.current && b.current) return 1
    return toTimestamp(b.date_active) - toTimestamp(a.date_active)
  })
  return list
})

const sortedOfficialMessages = computed(() => {
  const list = [...officialMessages.value]
  list.sort((a, b) => toTimestamp(b.date) - toTimestamp(a.date))
  return list
})

const loadDevices = async () => {
  const token = getAuthToken()
  if (!token || !props.accountName) return

  const seq = devicesGuard.next()
  loading.value = true
  error.value = ''
  try {
    const res = await listAccountDevices(token, props.accountName)
    if (!devicesGuard.isCurrent(seq)) return // 过期响应：账号已切换或弹窗已关闭
    devices.value = res.devices || []
  } catch (e: unknown) {
    if (!devicesGuard.isCurrent(seq)) return
    error.value = getLocalizedErrorMessage(e, t, t('accounts.loadDevicesFailed'))
  } finally {
    if (devicesGuard.isCurrent(seq)) loading.value = false
  }
}

const loadOfficialMessages = async () => {
  const token = getAuthToken()
  if (!token || !props.accountName) return

  const seq = officialGuard.next()
  officialLoading.value = true
  try {
    const res = await listAccountOfficialMessages(token, props.accountName, 10)
    if (!officialGuard.isCurrent(seq)) return // 过期响应：账号已切换或弹窗已关闭
    officialMessages.value = res.messages || []
  } catch {
    // 官方消息加载失败作为次要功能降级展示空，不遮断设备列表
    if (!officialGuard.isCurrent(seq)) return
    officialMessages.value = []
  } finally {
    if (officialGuard.isCurrent(seq)) officialLoading.value = false
  }
}

const refreshAll = async () => {
  await Promise.all([loadDevices(), loadOfficialMessages()])
}

const handleTerminate = async (device: AccountDeviceInfo) => {
  const label = device.device_model || device.app_name || device.hash
  const ok = await confirm({
    title: t('accounts.terminateDeviceConfirmTitle'),
    message: t('accounts.terminateDeviceConfirm', { name: label }),
    confirmText: t('accounts.terminateDevice'),
    danger: true,
  })
  if (!ok) return

  const token = getAuthToken()
  if (!token || !props.accountName) return

  terminatingHash.value = device.hash
  error.value = ''
  successMessage.value = ''
  try {
    const res = await terminateAccountDevice(token, props.accountName, device.hash)
    successMessage.value = res.message || t('accounts.terminateDeviceSuccess')
    devices.value = devices.value.filter((d) => d.hash !== device.hash)
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('accounts.terminateDeviceFailed'))
  } finally {
    terminatingHash.value = ''
  }
}

const handleResetOthers = async () => {
  const ok = await confirm({
    title: t('accounts.resetOtherDevicesConfirmTitle'),
    message: t('accounts.resetOtherDevicesConfirm'),
    confirmText: t('accounts.resetOtherDevices'),
    danger: true,
  })
  if (!ok) return

  const token = getAuthToken()
  if (!token || !props.accountName) return

  resettingOthers.value = true
  error.value = ''
  successMessage.value = ''
  try {
    const res = await resetOtherDevices(token, props.accountName)
    successMessage.value = res.message || t('accounts.resetOtherDevicesSuccess')
    await refreshAll()
    emit('reset-others')
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('accounts.resetOtherDevicesFailed'))
  } finally {
    resettingOthers.value = false
  }
}

watch(
  () => [props.isOpen, props.accountName] as const,
  ([open, name]) => {
    if (open && name) {
      refreshAll()
    } else if (!open) {
      devicesGuard.invalidate()
      officialGuard.invalidate()
      devices.value = []
      officialMessages.value = []
      error.value = ''
      successMessage.value = ''
      terminatingHash.value = ''
      exportedModalOpen.value = false
      exportedSessionString.value = ''
      copied.value = false
    }
  },
  { immediate: true },
)

onUnmounted(() => {
  devicesGuard.invalidate()
  officialGuard.invalidate()
  if (copyResetTimer !== null) {
    clearTimeout(copyResetTimer)
    copyResetTimer = null
  }
})
</script>

<template>
  <Modal :isOpen="isOpen" :title="title" maxWidthClass="max-w-3xl" @close="emit('close')">
    <template #header-extra>
      <span class="text-[11px] text-gray-500">{{ devices.length }} {{ t('accounts.deviceCount') }}</span>
    </template>

    <div class="space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <p class="text-xs text-gray-500 leading-relaxed">
          {{ t('accounts.devicesHint') }}
        </p>
        <div class="flex items-center gap-2 shrink-0">
          <button
            type="button"
            class="ui-btn-secondary shrink-0 !px-3 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="loading || resettingOthers || exportingSession"
            @click="handleExportSession"
          >
            <RefreshCw v-if="exportingSession" class="w-3.5 h-3.5 animate-spin" />
            <Download v-else class="w-3.5 h-3.5" />
            {{ t("accounts.exportStandaloneSessionShort") }}
          </button>
          <button
            type="button"
            class="ui-btn-danger shrink-0 !px-3 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="loading || resettingOthers"
            @click="handleResetOthers"
          >
            <RefreshCw v-if="resettingOthers" class="w-3.5 h-3.5 animate-spin" />
            <LogOut v-else class="w-3.5 h-3.5" />
            {{ t('accounts.resetOtherDevices') }}
          </button>
          <button
            type="button"
            class="ui-btn-secondary shrink-0 !px-3 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="loading || resettingOthers"
            @click="refreshAll"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading || officialLoading }" />
            {{ t('accounts.refreshDevices') }}
          </button>
        </div>
      </div>

      <div
        v-if="error"
        class="text-xs text-red-600 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg p-3"
      >
        {{ error }}
      </div>

      <div
        v-if="successMessage"
        class="text-xs text-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 rounded-lg p-3"
      >
        {{ successMessage }}
      </div>

      <div class="space-y-4">
        <div>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs font-semibold text-gray-700 dark:text-gray-300">
              {{ t('accounts.authorizedDevices') }} ({{ devices.length }})
            </h4>
          </div>

          <div
            v-if="loading && devices.length === 0"
            class="py-10 text-center text-xs text-gray-400"
          >
            <RefreshCw class="w-4 h-4 animate-spin mx-auto mb-2 text-primary-500" />
            {{ t('accounts.loadingDevices') }}
          </div>

          <div
            v-else-if="devices.length === 0"
            class="py-8 text-center text-xs text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg"
          >
            {{ t('accounts.noDevices') }}
          </div>

          <div v-else class="space-y-2 max-h-[300px] overflow-y-auto pr-1">
            <div
              v-for="device in sortedDevices"
              :key="device.hash"
              class="border rounded-lg p-3 text-xs transition-colors"
              :class="
                device.current
                  ? 'border-primary-500/40 bg-primary-50/30 dark:bg-primary-950/20'
                  : 'border-gray-200 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/40'
              "
            >
              <div class="flex items-start justify-between gap-3">
                <div class="space-y-1 min-w-0 flex-1">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium text-gray-900 dark:text-gray-100 truncate">
                      {{ device.device_model || t('accounts.unknownDevice') }}
                    </span>
                    <span
                      v-if="device.current"
                      class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-primary-100 text-primary-700 dark:bg-primary-900/60 dark:text-primary-300"
                    >
                      {{ t('accounts.currentDevice') }}
                    </span>
                    <span
                      v-if="device.official_app"
                      class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/60 dark:text-emerald-300"
                    >
                      {{ t('accounts.officialApp') }}
                    </span>
                    <span
                      v-if="device.password_pending"
                      class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300"
                    >
                      {{ t('accounts.passwordPending') }}
                    </span>
                  </div>

                  <div class="text-[11px] text-gray-500 space-x-2">
                    <span>{{ device.app_name }} {{ device.app_version }}</span>
                    <span>•</span>
                    <span>{{ device.platform }} {{ device.system_version }}</span>
                  </div>

                  <div class="text-[11px] text-gray-400 space-x-2 flex-wrap">
                    <span>IP: {{ device.ip || '-' }} ({{ device.country || '-' }})</span>
                    <span>•</span>
                    <span>{{ t('accounts.lastActive') }}: {{ formatDateTime(device.date_active) }}</span>
                    <span>•</span>
                    <span>{{ t('accounts.createdDate') }}: {{ formatDateTime(device.date_created) }}</span>
                  </div>
                </div>

                <div v-if="!device.current" class="shrink-0">
                  <button
                    type="button"
                    class="ui-btn-danger !px-2 !py-1 !text-[11px] inline-flex items-center gap-1"
                    :disabled="terminatingHash === device.hash || loading || resettingOthers"
                    @click="handleTerminate(device)"
                  >
                    <RefreshCw
                      v-if="terminatingHash === device.hash"
                      class="w-3 h-3 animate-spin"
                    />
                    <Trash2 v-else class="w-3 h-3" />
                    {{ t('accounts.terminateDevice') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between mb-2">
            <h4 class="text-xs font-semibold text-gray-700 dark:text-gray-300 inline-flex items-center gap-1.5">
              <ShieldCheck class="w-3.5 h-3.5 text-primary-500" />
              {{ t('accounts.officialMessagesTitle') }}
            </h4>
            <span class="text-[10px] text-gray-400">{{ t('accounts.officialMessagesHint') }}</span>
          </div>

          <div
            v-if="officialLoading && officialMessages.length === 0"
            class="py-6 text-center text-xs text-gray-400"
          >
            <RefreshCw class="w-3.5 h-3.5 animate-spin mx-auto mb-1 text-primary-500" />
            {{ t('accounts.loadingOfficialMessages') }}
          </div>

          <div
            v-else-if="officialMessages.length === 0"
            class="py-6 text-center text-xs text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg"
          >
            {{ t('accounts.noOfficialMessages') }}
          </div>

          <div v-else class="space-y-2 max-h-[220px] overflow-y-auto pr-1">
            <div
              v-for="(msg, index) in sortedOfficialMessages"
              :key="msg.id ?? index"
              class="border border-gray-200 dark:border-gray-800 rounded-lg p-3 text-xs bg-gray-50/60 dark:bg-gray-800/30"
            >
              <div class="flex items-center justify-between gap-2 text-[11px] text-gray-400 mb-1">
                <span class="font-mono">#{{ msg.id ?? '-' }}</span>
                <span>{{ formatDateTime(msg.date) }}</span>
              </div>
              <p class="text-gray-800 dark:text-gray-200 whitespace-pre-wrap leading-relaxed break-words">
                {{ msg.text }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="ui-btn-secondary !px-4 !py-1.5 !text-xs"
          @click="emit('close')"
        >
          {{ t('common.close') }}
        </button>
      </div>
    </template>
  </Modal>

  <!-- 派生独立 SessionString 导出展示弹窗 -->
  <Modal
    :isOpen="exportedModalOpen"
    :title="t('accounts.exportStandaloneSessionTitle')"
    maxWidthClass="max-w-xl"
    @close="exportedModalOpen = false"
  >
    <div class="space-y-3 text-xs">
      <p class="text-gray-600 dark:text-gray-400 leading-relaxed">
        {{ t("accounts.exportStandaloneSessionNotice") }}
      </p>

      <div class="grid grid-cols-2 gap-2 text-[11px] bg-gray-50 dark:bg-gray-800/60 p-2.5 rounded border border-gray-200 dark:border-gray-700">
        <div><span class="text-gray-400">DC ID:</span> <span class="font-mono font-medium">{{ exportedDcId ?? "-" }}</span></div>
        <div><span class="text-gray-400">User ID:</span> <span class="font-mono font-medium">{{ exportedUserId ?? "-" }}</span></div>
      </div>

      <div>
        <label class="block text-[11px] font-medium text-gray-500 mb-1">
          Pyrogram / Kurigram SessionString
        </label>
        <textarea
          readonly
          rows="4"
          class="w-full font-mono text-[11px] p-2 rounded border border-gray-300 dark:border-gray-700 bg-gray-100 dark:bg-gray-900 select-all break-all"
          :value="exportedSessionString"
        />
      </div>
    </div>

    <template #footer>
      <div class="flex items-center justify-between w-full">
        <button
          type="button"
          class="ui-btn-secondary !px-3 !py-1.5 !text-xs inline-flex items-center gap-1.5"
          @click="downloadSessionFile"
        >
          <Download class="w-3.5 h-3.5" />
          {{ t("accounts.downloadSessionFile") }}
        </button>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="ui-btn-primary !px-3 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            @click="copySessionString"
          >
            <Check v-if="copied" class="w-3.5 h-3.5 text-emerald-400" />
            <Copy v-else class="w-3.5 h-3.5" />
            {{ copied ? t("common.copied") : t("common.copy") }}
          </button>
          <button
            type="button"
            class="ui-btn-secondary !px-3 !py-1.5 !text-xs"
            @click="exportedModalOpen = false"
          >
            {{ t("common.close") }}
          </button>
        </div>
      </div>
    </template>
  </Modal>
</template>
