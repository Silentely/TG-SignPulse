<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Settings2, KeyRound, Bot, Sparkles, Database } from 'lucide-vue-next'
import { getGlobalSettings, saveGlobalSettings, getTelegramConfig, saveTelegramConfig, resetTelegramConfig, getAIConfig, saveAIConfig, testAIConnection, exportAllConfigs, importAllConfigs, runDeviceKeepalive, getBackupStatus, exportBackupArchive, getRuntimeStatus } from '../lib/api'
import type { BackupStatus, RuntimeStatus } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import CustomSelect from '../components/CustomSelect.vue'
import { useAuthStore } from '../stores/auth'
import { getLocalizedErrorMessage } from '../lib/types'
import { devLog } from '../lib/devLog'

const { t } = useI18n()
const toast = useToast()
const { confirm } = useConfirm()
const authStore = useAuthStore()

const settings = ref({
  checkInterval: '',
  logDays: 7,
  dataDir: '',
  proxy: '',
  concurrency: 1,
  deviceKeepaliveEnabled: true,
  deviceKeepaliveIntervalDays: 30,
  botEnabled: false,
  botLoginNotify: false,
  botTaskFailure: false,
  botToken: '',
  botChatId: '',
  botThreadId: '',
  timezone: 'Asia/Hong_Kong'
})

// 时区选项列表
const timezoneOptions = [
  { label: 'Asia/Shanghai (UTC+8)', value: 'Asia/Shanghai' },
  { label: 'Asia/Hong_Kong (UTC+8)', value: 'Asia/Hong_Kong' },
  { label: 'Asia/Tokyo (UTC+9)', value: 'Asia/Tokyo' },
  { label: 'Asia/Seoul (UTC+9)', value: 'Asia/Seoul' },
  { label: 'Asia/Singapore (UTC+8)', value: 'Asia/Singapore' },
  { label: 'Asia/Taipei (UTC+8)', value: 'Asia/Taipei' },
  { label: 'Asia/Bangkok (UTC+7)', value: 'Asia/Bangkok' },
  { label: 'Asia/Dubai (UTC+4)', value: 'Asia/Dubai' },
  { label: 'Asia/Kolkata (UTC+5:30)', value: 'Asia/Kolkata' },
  { label: 'Australia/Sydney (UTC+10/+11)', value: 'Australia/Sydney' },
  { label: 'America/New_York (UTC-5/-4)', value: 'America/New_York' },
  { label: 'America/Chicago (UTC-6/-5)', value: 'America/Chicago' },
  { label: 'America/Denver (UTC-7/-6)', value: 'America/Denver' },
  { label: 'America/Los_Angeles (UTC-8/-7)', value: 'America/Los_Angeles' },
  { label: 'America/Sao_Paulo (UTC-3)', value: 'America/Sao_Paulo' },
  { label: 'Europe/London (UTC+0/+1)', value: 'Europe/London' },
  { label: 'Europe/Berlin (UTC+1/+2)', value: 'Europe/Berlin' },
  { label: 'Europe/Paris (UTC+1/+2)', value: 'Europe/Paris' },
  { label: 'Europe/Moscow (UTC+3)', value: 'Europe/Moscow' },
  { label: 'Africa/Cairo (UTC+2)', value: 'Africa/Cairo' },
  { label: 'Pacific/Auckland (UTC+12/+13)', value: 'Pacific/Auckland' },
  { label: 'UTC', value: 'UTC' },
]

const tgConfig = ref({
  api_id: '',
  api_hash: ''
})

const aiConfig = ref({
  base_url: '',
  model: '',
  api_key: ''
})

const loading = ref(false)
const tgLoading = ref(false)
const aiLoading = ref(false)
const dataLoading = ref(false)
const backupLoading = ref(false)
const backupStatus = ref<BackupStatus | null>(null)
const runtimeStatus = ref<RuntimeStatus | null>(null)
const pageLoading = ref(true)

const notifySuccess = (msg: string) => toast.success(msg)
const notifyError = (msg: string) => toast.error(msg)

onMounted(async () => {
  const token = authStore.token || ''
  if (!token) {
    pageLoading.value = false
    return
  }

  try {
    const [res, tgRes, aiRes] = await Promise.all([
      getGlobalSettings(token),
      getTelegramConfig(token).catch(() => null),
      getAIConfig(token).catch(() => null)
    ])
    settings.value.checkInterval = res.sign_interval ? String(res.sign_interval) : ''
    settings.value.logDays = res.log_retention_days || 7
    settings.value.dataDir = res.data_dir || ''
    settings.value.proxy = res.global_proxy || ''
    settings.value.concurrency = res.tg_global_concurrency || 1
    settings.value.deviceKeepaliveEnabled = res.device_keepalive_enabled !== false
    settings.value.deviceKeepaliveIntervalDays = res.device_keepalive_interval_days || 30
    settings.value.botEnabled = res.telegram_bot_notify_enabled || false
    settings.value.botLoginNotify = res.telegram_bot_login_notify_enabled || false
    settings.value.botTaskFailure = res.telegram_bot_task_failure_enabled || false
    settings.value.botToken = res.telegram_bot_token || ''
    settings.value.botChatId = res.telegram_bot_chat_id || ''
    settings.value.botThreadId = res.telegram_bot_message_thread_id ? String(res.telegram_bot_message_thread_id) : ''
    settings.value.timezone = res.timezone || 'Asia/Hong_Kong'

    if (tgRes && tgRes.is_custom) {
      tgConfig.value.api_id = tgRes.api_id
      tgConfig.value.api_hash = tgRes.api_hash
    }

    if (aiRes && aiRes.has_config) {
      aiConfig.value.base_url = aiRes.base_url || ''
      aiConfig.value.model = aiRes.model || ''
    }

    try {
      backupStatus.value = await getBackupStatus(token)
    } catch (e) {
      devLog.error('Failed to load backup status', e)
    }
    try {
      runtimeStatus.value = await getRuntimeStatus(token)
    } catch (e) {
      devLog.error('Failed to load runtime status', e)
    }
  } catch (e) {
    devLog.error('Failed to load settings', e)
    notifyError(getLocalizedErrorMessage(e, t, t('settings.loadFailed')))
  } finally {
    pageLoading.value = false
  }
})

const saveSettings = async () => {
  const token = authStore.token || ''
  if (!token) return

  loading.value = true
  try {
    await saveGlobalSettings(token, {
      sign_interval: settings.value.checkInterval ? parseInt(settings.value.checkInterval) : null,
      log_retention_days: settings.value.logDays,
      data_dir: settings.value.dataDir || null,
      global_proxy: settings.value.proxy || null,
      tg_global_concurrency: settings.value.concurrency || 1,
      device_keepalive_enabled: settings.value.deviceKeepaliveEnabled,
      device_keepalive_interval_days: settings.value.deviceKeepaliveIntervalDays || 30,
      timezone: settings.value.timezone,
    })
    notifySuccess(t('settings.saveSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    loading.value = false
  }
}

const botLoading = ref(false)
const keepaliveLoading = ref(false)

const runKeepaliveNow = async () => {
  const token = authStore.token || ''
  if (!token) return

  keepaliveLoading.value = true
  try {
    const res = await runDeviceKeepalive(token)
    notifySuccess(`${t('settings.keepaliveDone')}：${res.kept_alive}/${res.checked}，${t('settings.failed')} ${res.failed}`)
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.keepaliveFailed')))
  } finally {
    keepaliveLoading.value = false
  }
}

const saveBotSettings = async () => {
  const token = authStore.token || ''
  if (!token) return

  botLoading.value = true
  try {
    await saveGlobalSettings(token, {
      telegram_bot_notify_enabled: settings.value.botEnabled,
      telegram_bot_login_notify_enabled: settings.value.botLoginNotify,
      telegram_bot_task_failure_enabled: settings.value.botTaskFailure,
      telegram_bot_token: settings.value.botToken || null,
      telegram_bot_chat_id: settings.value.botChatId || null,
      telegram_bot_message_thread_id: settings.value.botThreadId ? parseInt(settings.value.botThreadId) : null,
    })
    notifySuccess(t('settings.saveSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    botLoading.value = false
  }
}

const saveTgConfig = async () => {
  const token = authStore.token || ''
  tgLoading.value = true
  try {
    await saveTelegramConfig(token, { api_id: tgConfig.value.api_id, api_hash: tgConfig.value.api_hash })
    notifySuccess(t('settings.tgConfigSaved'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    tgLoading.value = false
  }
}

const resetTgConfig = async () => {
  const token = authStore.token || ''
  const ok = await confirm({
    title: t('settings.resetDefault'),
    message: t('settings.resetConfirm'),
    confirmText: t('common.continue'),
    danger: true,
  })
  if (!ok) return
  tgLoading.value = true
  try {
    await resetTelegramConfig(token)
    tgConfig.value.api_id = ''
    tgConfig.value.api_hash = ''
    notifySuccess(t('settings.resetSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.resetFailed')))
  } finally {
    tgLoading.value = false
  }
}

const saveAiConfig = async () => {
  const token = authStore.token || ''
  aiLoading.value = true
  try {
    await saveAIConfig(token, {
      base_url: aiConfig.value.base_url || undefined,
      model: aiConfig.value.model || undefined,
      api_key: aiConfig.value.api_key || undefined
    })
    notifySuccess(t('settings.aiConfigSaved'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    aiLoading.value = false
  }
}

const testAi = async () => {
  const token = authStore.token || ''
  aiLoading.value = true
  try {
    const res = await testAIConnection(token)
    notifySuccess(res.message || t('settings.testSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.testFailed')))
  } finally {
    aiLoading.value = false
  }
}

const handleExport = async () => {
  const token = authStore.token || ''
  dataLoading.value = true
  try {
    const jsonStr = await exportAllConfigs(token)
    const blob = new Blob([jsonStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tg-signpulse-export-${new Date().toISOString().split('T')[0]}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    notifySuccess(t('settings.exportSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.exportFailed')))
  } finally {
    dataLoading.value = false
  }
}

const handleBackupExport = async () => {
  const token = authStore.token || ''
  backupLoading.value = true
  try {
    await exportBackupArchive(token)
    notifySuccess(t('settings.backupExportSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.backupExportFailed')))
  } finally {
    backupLoading.value = false
  }
}

const handleImport = async (e: Event) => {
  const target = e.target as HTMLInputElement
  if (!target.files || !target.files[0]) return
  const file = target.files[0]
  const reader = new FileReader()
  reader.onload = async (ev) => {
    const jsonStr = ev.target?.result as string
    const token = authStore.token || ''
    dataLoading.value = true
    try {
      const result = await importAllConfigs(token, jsonStr, true)
      const warnings = result.warnings || []
      const errors = result.errors || []
      const summary = [
        result.message,
        warnings.length ? warnings.slice(0, 3).join('; ') : '',
        errors.length ? errors.slice(0, 3).join('; ') : '',
      ]
        .filter(Boolean)
        .join(' · ')
      if (errors.length) {
        notifyError(`${t('settings.importWithErrors')}: ${summary}`)
      } else if (warnings.length) {
        notifySuccess(`${t('settings.importPartial')}: ${summary}`)
      } else {
        notifySuccess(t('settings.importSuccess'))
      }
    } catch (err: unknown) {
      notifyError(getLocalizedErrorMessage(err, t, t('settings.importFailed')))
    } finally {
      dataLoading.value = false
      target.value = ''
    }
  }
  reader.readAsText(file)
}
</script>

<template>
  <div class="max-w-7xl pb-10">
    <div v-if="pageLoading" class="grid grid-cols-1 lg:grid-cols-2 gap-6" aria-busy="true">
      <div v-for="i in 4" :key="i" class="ui-card p-6 space-y-4">
        <div class="ui-skeleton h-5 w-32" />
        <div class="ui-skeleton h-3 w-48" />
        <div class="ui-skeleton h-10 w-full" />
        <div class="ui-skeleton h-10 w-full" />
        <div class="ui-skeleton h-10 w-2/3" />
      </div>
    </div>
    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      
      <!-- 通用设置 + Telegram API（左列） -->
      <div class="flex flex-col gap-6">
        <!-- 通用设置 -->
        <section class="ui-card p-6">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <span class="ui-section-icon" aria-hidden="true"><Settings2 class="w-3.5 h-3.5" /></span>
              <div class="min-w-0">
                <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.general') }}</h2>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.generalDesc') }}</p>
              </div>
            </div>
            <span v-if="loading" class="text-xs text-gray-500 shrink-0">{{ t('settings.saving') }}</span>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.logRetention') }}</label>
              <input v-model="settings.logDays" type="number" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.dataDir') }}</label>
              <input v-model="settings.dataDir" type="text" placeholder="/data" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.proxy') }}</label>
              <input v-model="settings.proxy" type="text" placeholder="socks5://127.0.0.1:1080" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.concurrency') }}</label>
              <input v-model.number="settings.concurrency" type="number" min="1" max="10" :placeholder="t('settings.concurrencyPlaceholder')" class="ui-input">
            </div>
            <div class="p-3 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/60 space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <label class="text-xs text-gray-600 dark:text-gray-300 block">{{ t('settings.deviceKeepalive') }}</label>
                  <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.deviceKeepaliveDesc') }}</p>
                </div>
                <button
                  type="button"
                  class="ui-switch"
                  role="switch"
                  :aria-checked="settings.deviceKeepaliveEnabled"
                  :class="settings.deviceKeepaliveEnabled ? 'ui-switch-on' : ''"
                  @click="settings.deviceKeepaliveEnabled = !settings.deviceKeepaliveEnabled"
                >
                  <span class="ui-switch-knob" />
                </button>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2">
                <input v-model.number="settings.deviceKeepaliveIntervalDays" type="number" min="1" max="170" :disabled="!settings.deviceKeepaliveEnabled" class="ui-input disabled:opacity-50">
                <button type="button" class="ui-btn-secondary !px-3 !py-2 !text-xs" :disabled="keepaliveLoading" @click="runKeepaliveNow">
                  {{ keepaliveLoading ? t('settings.saving') : t('settings.keepaliveNow') }}
                </button>
              </div>
              <p class="text-[10px] text-gray-500">{{ t('settings.deviceKeepaliveIntervalHint') }}</p>
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.timezone') }}</label>
              <CustomSelect v-model="settings.timezone" :options="timezoneOptions" className="w-full" />
            </div>
            <div class="pt-2">
              <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="loading" @click="saveSettings">{{ loading ? t('settings.saving') : t('settings.saveGeneral') }}</button>
            </div>
          </div>
        </section>

        <!-- Telegram API -->
        <section class="ui-card p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <span class="ui-section-icon" aria-hidden="true"><KeyRound class="w-3.5 h-3.5" /></span>
              <div class="min-w-0">
                <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.tgApi') }}</h2>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.tgApiDesc') }}</p>
              </div>
            </div>
            <button type="button" class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0" :disabled="tgLoading" @click="resetTgConfig">{{ t('settings.resetDefault') }}</button>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="ui-label">API ID</label>
              <input v-model="tgConfig.api_id" type="password" class="ui-input" autocomplete="off">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">API Hash</label>
              <input v-model="tgConfig.api_hash" type="password" class="ui-input">
            </div>
            <div class="p-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
              <p>
                {{ t('settings.apiWarning') }}
                <a href="https://my.telegram.org/auth" target="_blank" rel="noopener noreferrer" class="underline hover:text-amber-900 dark:hover:text-amber-300 font-medium">my.telegram.org</a>
              </p>
            </div>
            <div class="pt-2">
              <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="tgLoading || !tgConfig.api_id || !tgConfig.api_hash" @click="saveTgConfig">{{ tgLoading ? t('settings.saving') : t('settings.saveTgConfig') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- AI 配置 + Bot 通知（右列） -->
      <div class="flex flex-col gap-6">
        <!-- AI 模型配置 -->
        <section class="ui-card p-6">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <span class="ui-section-icon" aria-hidden="true"><Sparkles class="w-3.5 h-3.5" /></span>
              <div class="min-w-0">
                <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.aiConfig') }}</h2>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.aiDesc') }}</p>
              </div>
            </div>
            <button type="button" class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0" :disabled="aiLoading" @click="testAi">{{ t('settings.testConnection') }}</button>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.apiBaseUrl') }}</label>
              <input v-model="aiConfig.base_url" type="text" placeholder="https://api.openai.com/v1" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.model') }}</label>
              <input v-model="aiConfig.model" type="text" placeholder="gpt-4" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.apiKey') }}</label>
              <input v-model="aiConfig.api_key" type="password" placeholder="sk-..." class="ui-input">
            </div>
            <div class="pt-2">
              <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="aiLoading" @click="saveAiConfig">{{ aiLoading ? t('settings.saving') : t('settings.saveAiConfig') }}</button>
            </div>
          </div>
        </section>

        <!-- Telegram 机器人通知 -->
        <section class="ui-card p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <span class="ui-section-icon" aria-hidden="true"><Bot class="w-3.5 h-3.5" /></span>
              <div class="min-w-0">
                <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.botNotify') }}</h2>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.botDesc') }}</p>
              </div>
            </div>
            <button 
              type="button"
              class="ui-switch shrink-0"
              role="switch"
              :aria-checked="settings.botEnabled"
              :class="settings.botEnabled ? 'ui-switch-on' : ''"
              @click="settings.botEnabled = !settings.botEnabled"
            >
              <span class="ui-switch-knob" />
            </button>
          </div>

          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.botToken') }}</label>
              <input v-model="settings.botToken" type="password" placeholder="123456:ABC-DEF..." class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.targetChatId') }}</label>
              <input v-model="settings.botChatId" type="text" placeholder="-1001234567890" class="ui-input">
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.threadId') }}</label>
              <input v-model="settings.botThreadId" type="text" :placeholder="t('settings.threadIdPlaceholder')" class="ui-input">
            </div>
            <div class="flex flex-wrap gap-x-6 gap-y-3 pt-2">
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="settings.botLoginNotify" type="checkbox" class="w-4 h-4 accent-sky-500 bg-gray-100 border-gray-300 rounded focus:ring-0 dark:bg-gray-800 dark:border-gray-600">
                <span class="text-sm text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors">{{ t('settings.loginFailNotify') }}</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="settings.botTaskFailure" type="checkbox" class="w-4 h-4 accent-sky-500 bg-gray-100 border-gray-300 rounded focus:ring-0 dark:bg-gray-800 dark:border-gray-600">
                <span class="text-sm text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors">{{ t('settings.taskFailNotify') }}</span>
              </label>
            </div>
            <div class="pt-2">
              <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="botLoading" @click="saveBotSettings">{{ botLoading ? t('settings.saving') : t('settings.saveChanges') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- 数据管理（全宽） -->
      <section class="ui-card p-6 lg:col-span-2">
        <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start gap-3">
          <span class="ui-section-icon" aria-hidden="true"><Database class="w-3.5 h-3.5" /></span>
          <div>
            <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.dataManagement') }}</h2>
            <p class="text-xs text-gray-500 mt-1">{{ t('settings.dataManagementDesc') }}</p>
          </div>
        </div>

        <!-- 配置迁移 JSON -->
        <div class="max-w-2xl space-y-3 mb-6">
          <div>
            <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.configMigrateTitle') }}</h3>
            <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.configMigrateDesc') }}</p>
          </div>
          <div class="flex flex-col sm:flex-row gap-3 max-w-lg">
            <button
              type="button"
              class="ui-btn-primary flex-1 !px-4 !py-2"
              :disabled="dataLoading"
              @click="handleExport"
            >
              {{ dataLoading ? t('settings.processing') : t('settings.exportJson') }}
            </button>
            <div class="relative flex-1">
              <input
                type="file"
                accept="application/json,.json"
                class="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
                :disabled="dataLoading"
                @change="handleImport"
              />
              <button
                type="button"
                class="ui-btn-secondary w-full !px-4 !py-2"
                :disabled="dataLoading"
              >
                {{ t('settings.importJson') }}
              </button>
            </div>
          </div>
        </div>

        <!-- 完整备份 -->
        <div class="pt-5 border-t border-gray-200 dark:border-gray-800/60 max-w-2xl space-y-3">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.fullBackup') }}</h3>
              <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.fullBackupDesc') }}</p>
            </div>
            <button
              type="button"
              class="ui-btn-secondary shrink-0 !px-4 !py-2"
              :disabled="backupLoading"
              @click="handleBackupExport"
            >
              {{ backupLoading ? t('settings.processing') : t('settings.exportBackup') }}
            </button>
          </div>
          <p v-if="backupStatus" class="text-xs text-gray-500 font-mono">
            {{ backupStatus.data_dir }} · {{ backupStatus.size_human }}
            · {{ backupStatus.writable ? t('settings.backupWritable') : t('settings.backupReadonly') }}
          </p>
          <p v-if="backupStatus?.restore_hint" class="text-xs text-amber-700 dark:text-amber-400/90">
            {{ t('settings.backupRestoreHint') }}: {{ backupStatus.restore_hint }}
          </p>
          <ul v-if="backupStatus?.notes?.length" class="text-xs text-gray-500 space-y-1 list-disc pl-4">
            <li v-for="(note, i) in backupStatus.notes" :key="i">{{ note }}</li>
          </ul>

          <div v-if="runtimeStatus" class="mt-4 p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-1.5">
            <div class="font-medium text-gray-700 dark:text-gray-300 mb-1">{{ t('settings.runtimeStatus') }}</div>
            <div class="text-gray-600 dark:text-gray-400">
              {{ t('settings.schedulerLock') }}:
              <span :class="runtimeStatus.scheduler_lock_held ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
                {{ runtimeStatus.scheduler_lock_held ? t('settings.lockHeld') : t('settings.lockNotHeld') }}
              </span>
            </div>
            <div class="text-gray-600 dark:text-gray-400">
              {{ t('settings.legacyWritable') }}:
              {{ runtimeStatus.legacy_tasks_writable ? t('settings.yes') : t('settings.no') }}
            </div>
            <div class="text-gray-600 dark:text-gray-400">
              DB: {{ runtimeStatus.database_is_sqlite ? 'SQLite' : 'External' }}
              <span v-if="runtimeStatus.monitor_shard"> · shard {{ runtimeStatus.monitor_shard }}</span>
            </div>
          </div>
        </div>
      </section>

    </div>
  </div>
</template>
