<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RefreshCw, ShieldCheck, Smartphone, Trash2 } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import { listAccountDevices, terminateAccountDevice, type AccountDeviceInfo } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  isOpen: boolean
  accountName: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { t } = useI18n()
const devices = ref<AccountDeviceInfo[]>([])
const loading = ref(false)
const error = ref('')
const terminatingHash = ref('')

const title = computed(() => `${t('accounts.devices')} · ${props.accountName || ''}`)

const formatDate = (value?: string | null) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

const deviceTitle = (device: AccountDeviceInfo) => {
  return [device.device_model, device.platform].filter(Boolean).join(' · ') || t('accounts.unknownDevice')
}

const deviceSubtitle = (device: AccountDeviceInfo) => {
  return [device.app_name, device.app_version, device.system_version].filter(Boolean).join(' · ') || '-'
}

const locationText = (device: AccountDeviceInfo) => {
  return [device.country, device.region, device.ip].filter(Boolean).join(' · ') || '-'
}

const loadDevices = async () => {
  if (!props.isOpen || !props.accountName) return
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return
  loading.value = true
  error.value = ''
  try {
    const res = await listAccountDevices(token, props.accountName)
    devices.value = res.devices || []
  } catch (e: any) {
    error.value = e?.message || t('accounts.devicesLoadFailed')
  } finally {
    loading.value = false
  }
}

const terminateDevice = async (device: AccountDeviceInfo) => {
  if (device.current) return
  if (!confirm(t('accounts.terminateDeviceConfirm'))) return
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return
  terminatingHash.value = device.hash
  error.value = ''
  try {
    await terminateAccountDevice(token, props.accountName, device.hash)
    await loadDevices()
  } catch (e: any) {
    error.value = e?.message || t('accounts.terminateDeviceFailed')
  } finally {
    terminatingHash.value = ''
  }
}

watch(() => props.isOpen, (open) => {
  if (open) loadDevices()
  else {
    devices.value = []
    error.value = ''
  }
})
</script>

<template>
  <Modal :isOpen="isOpen" :title="title" maxWidthClass="max-w-3xl" @close="emit('close')">
    <template #header-extra>
      <span class="text-[11px] text-gray-500">{{ devices.length }} {{ t('accounts.deviceCount') }}</span>
    </template>

    <div class="space-y-4">
      <div class="flex items-start justify-between gap-3">
        <p class="text-xs text-gray-500 leading-relaxed">
          {{ t('accounts.devicesHint') }}
        </p>
        <button
          @click="loadDevices"
          :disabled="loading"
          class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
          {{ t('accounts.refreshDevices') }}
        </button>
      </div>

      <div v-if="error" class="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border border-rose-100 dark:border-rose-500/20 px-3 py-2">
        {{ error }}
      </div>

      <div v-if="loading && devices.length === 0" class="flex items-center justify-center py-10 text-gray-400">
        <RefreshCw class="w-5 h-5 animate-spin" />
      </div>

      <div v-else-if="devices.length === 0" class="py-10 text-center text-sm text-gray-500 border border-dashed border-gray-200 dark:border-gray-800">
        {{ t('accounts.noDevices') }}
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="device in devices"
          :key="device.hash"
          class="border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-950 p-4"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0 flex items-start gap-3">
              <div class="mt-0.5 w-9 h-9 shrink-0 border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 flex items-center justify-center text-gray-500">
                <ShieldCheck v-if="device.current" class="w-4 h-4 text-emerald-500" />
                <Smartphone v-else class="w-4 h-4" />
              </div>
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-2">
                  <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
                    {{ deviceTitle(device) }}
                  </div>
                  <span v-if="device.current" class="text-[10px] px-1.5 py-0.5 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-500/20">
                    {{ t('accounts.currentDevice') }}
                  </span>
                  <span v-if="device.official_app" class="text-[10px] px-1.5 py-0.5 bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-100 dark:border-blue-500/20">
                    {{ t('accounts.officialApp') }}
                  </span>
                </div>
                <div class="text-xs text-gray-500 mt-1 truncate">{{ deviceSubtitle(device) }}</div>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3 text-[11px] text-gray-500">
                  <div><span class="text-gray-400">{{ t('accounts.lastActive') }}：</span>{{ formatDate(device.date_active) }}</div>
                  <div><span class="text-gray-400">{{ t('accounts.createdAt') }}：</span>{{ formatDate(device.date_created) }}</div>
                  <div class="truncate" :title="locationText(device)"><span class="text-gray-400">{{ t('accounts.location') }}：</span>{{ locationText(device) }}</div>
                </div>
              </div>
            </div>

            <button
              v-if="!device.current"
              @click="terminateDevice(device)"
              :disabled="terminatingHash === device.hash || loading"
              class="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-500/10 disabled:opacity-50"
            >
              <RefreshCw v-if="terminatingHash === device.hash" class="w-3.5 h-3.5 animate-spin" />
              <Trash2 v-else class="w-3.5 h-3.5" />
              {{ t('accounts.terminateDevice') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Modal>
</template>
