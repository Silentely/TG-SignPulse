/**
 * 系统设置页业务逻辑：加载/保存/脏检查/备份/版本检查。
 * Settings.vue 仅负责布局与子组件接线。
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import {
  getGlobalSettings,
  getTelegramConfig,
  getAIConfig,
  getRuntimeStatus,
  getMemoryStats,
} from '../lib/api'
import type { RuntimeStatus, MemoryStatsResponse } from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useAuthStore } from '../stores/auth'
import { resolveApiErrorMessage } from '../lib/notify'
import { devLog } from '../lib/devLog'
import {
  applyGlobalSettingsToForm,
  buildAdvancedPayload as buildAdvancedPayloadOf,
  buildAiRuntimePayload as buildAiRuntimePayloadOf,
  buildBackupPayload as buildBackupPayloadOf,
  buildBotPayload as buildBotPayloadOf,
  buildGeneralPayload as buildGeneralPayloadOf,
  dirtySectionLabels,
  isAnySectionDirty,
  snapAllSections,
  type SettingsSection,
  type SettingsFormState,
  type TgFormState,
  type AiFormState,
} from '../lib/settings-form'
import { useSettingsVersionCheck } from './useSettingsVersionCheck'
import { useSettingsBackup } from './useSettingsBackup'
import { useSettingsSave } from './useSettingsSave'

export function useSettingsPage() {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const authStore = useAuthStore()
  const notifySuccess = (msg: string) => toast.success(msg)
  const notifyError = (msg: string) => toast.error(msg)

  const settings = ref<SettingsFormState>({
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
    botTaskSuccess: false,
    quietEnabled: false,
    quietStart: '23:00',
    quietEnd: '07:00',
    botToken: '',
    botChatId: '',
    botThreadId: '',
    timezone: 'Asia/Hong_Kong',
    execTimeout: '' as string | number,
    accountCooldown: '' as string | number,
    flowRetry: '' as string | number,
    historyMaxAge: '' as string | number,
    aiVisionTimeout: '' as string | number,
    aiVisionRetry: '' as string | number,
    autoBackupEnabled: false,
    autoBackupInterval: 24,
    autoBackupKeep: 3,
    webdavUrl: '',
    webdavUsername: '',
    webdavPassword: '',
    webdavRemoteDir: 'tg-signpulse-backups',
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

  const tgConfig = ref<TgFormState>({
    api_id: '',
    api_hash: ''
  })

  const aiConfig = ref<AiFormState>({
    base_url: '',
    model: '',
    api_key: ''
  })
  /** 服务端 AI Key 解密失败标记（APP_SECRET_KEY 不匹配） */
  const aiKeyDecryptFailed = ref(false)

  const runtimeStatus = ref<RuntimeStatus | null>(null)
  const memoryStats = ref<MemoryStatsResponse | null>(null)
  const pageLoading = ref(true)
  const botTokenSet = ref(false)
  const afterBotTokenSaved = () => {
    if (settings.value.botToken) {
      botTokenSet.value = true
      settings.value.botToken = ''
    }
  }
  /** 密钥字段显隐（默认隐藏） */
  const revealSecrets = ref({
    tgApiId: false,
    tgApiHash: false,
    aiKey: false,
    botToken: false,
  })

  /** 分段脏检查基线（分块保存只清对应段） */
  const sectionBaseline = ref<Record<SettingsSection, string> | null>(null)

  const currentSectionSnaps = () =>
    snapAllSections(settings.value, tgConfig.value, aiConfig.value)

  const markAllClean = () => {
    sectionBaseline.value = currentSectionSnaps()
  }

  const markSectionClean = (section: SettingsSection) => {
    if (!sectionBaseline.value) {
      markAllClean()
      return
    }
    sectionBaseline.value = {
      ...sectionBaseline.value,
      [section]: snapSectionFor(section),
    }
  }

  const snapSectionFor = (section: SettingsSection) =>
    currentSectionSnaps()[section]

  const isDirty = computed(() =>
    isAnySectionDirty(sectionBaseline.value, currentSectionSnaps()),
  )

  const dirtyLabels = computed(() =>
    dirtySectionLabels(sectionBaseline.value, currentSectionSnaps(), {
      general: t('settings.general'),
      bot: t('settings.botNotify'),
      // advanced 段仅含备份/WebDAV（数据管理）
      advanced: t('settings.dataManagement'),
      tg: t('settings.tgApi'),
      ai: t('settings.aiConfig'),
    }),
  )

  const onBeforeUnload = (e: BeforeUnloadEvent) => {
    if (!isDirty.value) return
    e.preventDefault()
    e.returnValue = ''
  }

  onBeforeRouteLeave(async () => {
    if (!isDirty.value) return true
    const ok = await confirm({
      title: t('settings.unsavedTitle'),
      message: t('settings.unsavedMessage'),
      confirmText: t('settings.leaveAnyway'),
      danger: true,
    })
    return ok
  })

  const {
    appVersion,
    versionLoading,
    checkLoading,
    versionBanner,
    loadVersion,
    handleCheckUpdate,
  } = useSettingsVersionCheck()

  const buildGeneralPayload = () => buildGeneralPayloadOf(settings.value)
  const buildBotPayload = () => buildBotPayloadOf(settings.value)
  const buildAdvancedPayload = () => buildAdvancedPayloadOf(settings.value)
  const buildAiRuntimePayload = () => buildAiRuntimePayloadOf(settings.value)
  const buildBackupPayload = () => buildBackupPayloadOf(settings.value)

  const {
    dataLoading,
    backupLoading,
    backupStatus,
    webdavTestLoading,
    webdavListLoading,
    remoteWebdavFiles,
    remoteWebdavMessage,
    webdavPasswordSet,
    remoteDownloadName,
    afterWebdavSettingsSaved,
    handleExport,
    handleListRemoteBackups,
    handleDownloadRemoteBackup,
    handleBackupExport,
    handleWebdavTest,
    handleImportFile,
    loadBackupStatus,
  } = useSettingsBackup({
    settings,
    buildBackupPayload,
    markSectionClean: (section) => markSectionClean(section),
    notifySuccess,
    notifyError,
  })

  const {
    loading,
    botLoading,
    advancedLoading,
    saveAllLoading,
    tgLoading,
    aiLoading,
    botTestLoading,
    keepaliveLoading,
    saveSettings,
    runKeepaliveNow,
    saveBotSettings,
    saveAdvancedSettings,
    saveAllSettings,
    testBot,
    saveTgConfig,
    resetTgConfig,
    saveAiConfig,
    testAi,
  } = useSettingsSave({
    tgConfig,
    aiConfig,
    aiKeyDecryptFailed,
    buildGeneralPayload,
    buildBotPayload,
    buildAdvancedPayload,
    buildAiRuntimePayload,
    buildBackupPayload,
    markSectionClean,
    afterBotTokenSaved,
    afterWebdavSettingsSaved,
    loadBackupStatus,
    notifySuccess,
    notifyError,
  })

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
      const flags = applyGlobalSettingsToForm(settings.value, res)
      botTokenSet.value = flags.botTokenSet
      webdavPasswordSet.value = flags.webdavPasswordSet

      if (tgRes && tgRes.is_custom) {
        tgConfig.value.api_id = tgRes.api_id
        tgConfig.value.api_hash = tgRes.api_hash
      }

      if (aiRes && aiRes.has_config) {
        aiConfig.value.base_url = aiRes.base_url || ''
        aiConfig.value.model = aiRes.model || ''
        aiKeyDecryptFailed.value = !!aiRes.api_key_decrypt_failed
      } else {
        aiKeyDecryptFailed.value = false
      }

      try {
        await loadBackupStatus(token)
      } catch (e: unknown) {
        devLog.error('Failed to load backup status', e)
      }
      try {
        runtimeStatus.value = await getRuntimeStatus(token)
      } catch (e: unknown) {
        devLog.error('Failed to load runtime status', e)
      }
      try {
        memoryStats.value = await getMemoryStats(token)
      } catch (e: unknown) {
        devLog.error('Failed to load memory stats', e)
      }
      await loadVersion(token)
      markAllClean()
      window.addEventListener('beforeunload', onBeforeUnload)
    } catch (e: unknown) {
      devLog.error('Failed to load settings', e)
      notifyError(resolveApiErrorMessage(e, 'settings.loadFailed'))
    } finally {
      pageLoading.value = false
    }
  })

  onUnmounted(() => {
    window.removeEventListener('beforeunload', onBeforeUnload)
  })


  const toggleReveal = (key: 'tgApiId' | 'tgApiHash' | 'aiKey' | 'botToken') => {
    revealSecrets.value = {
      ...revealSecrets.value,
      [key]: !revealSecrets.value[key],
    }
  }

  return {
    t,
    settings,
    timezoneOptions,
    tgConfig,
    aiConfig,
    aiKeyDecryptFailed,
    loading,
    tgLoading,
    aiLoading,
    dataLoading,
    backupLoading,
    backupStatus,
    runtimeStatus,
    memoryStats,
    advancedLoading,
    botTestLoading,
    pageLoading,
    revealSecrets,
    isDirty,
    dirtyLabels,
    appVersion,
    versionLoading,
    checkLoading,
    versionBanner,
    botLoading,
    keepaliveLoading,
    saveAllLoading,
    webdavTestLoading,
    webdavListLoading,
    remoteWebdavFiles,
    remoteWebdavMessage,
    webdavPasswordSet,
    botTokenSet,
    remoteDownloadName,
    saveSettings,
    runKeepaliveNow,
    saveBotSettings,
    saveAdvancedSettings,
    saveAllSettings,
    testBot,
    saveTgConfig,
    resetTgConfig,
    saveAiConfig,
    testAi,
    handleExport,
    handleImportFile,
    handleBackupExport,
    handleWebdavTest,
    handleListRemoteBackups,
    handleDownloadRemoteBackup,
    handleCheckUpdate,
    toggleReveal,
  }
}
