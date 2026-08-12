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
import { getAuthToken } from '../lib/api/core'
import type { RuntimeStatus, MemoryStatsResponse } from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { resolveApiErrorMessage } from '../lib/notify'
import { setPanelTimezone } from '../lib/datetime'
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
  /** 全局设置加载失败标记：失败时展示错误态与重试，而非默认空表单 */
  const loadFailed = ref(false)
  // 卸载标记：异步加载期间离开页面时停止后续副作用
  let disposed = false
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
  })

  const loadAllSettings = async () => {
    const token = getAuthToken()
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
      // 同步面板展示时区：Settings 加载后，Dashboard/Logs 等页的时间格式跟随
      setPanelTimezone(res.timezone)

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

      // 运行信息互不依赖，并行请求可以减少设置页首屏等待；单项失败仍然降级。
      const [backupResult, runtimeResult, memoryResult, versionResult] =
        await Promise.allSettled([
          loadBackupStatus(token),
          getRuntimeStatus(token),
          getMemoryStats(token),
          loadVersion(token),
        ])
      if (backupResult.status === 'rejected') {
        devLog.error('Failed to load backup status', backupResult.reason)
      }
      if (runtimeResult.status === 'fulfilled') {
        runtimeStatus.value = runtimeResult.value
      } else {
        devLog.error('Failed to load runtime status', runtimeResult.reason)
      }
      if (memoryResult.status === 'fulfilled') {
        memoryStats.value = memoryResult.value
      } else {
        devLog.error('Failed to load memory stats', memoryResult.reason)
      }
      if (versionResult.status === 'rejected') {
        devLog.error('Failed to load app version', versionResult.reason)
      }
      if (disposed) return // 加载期间已卸载：不再标记干净或注册监听
      markAllClean()
      loadFailed.value = false
    } catch (e: unknown) {
      devLog.error('Failed to load settings', e)
      loadFailed.value = true
      toast.error(resolveApiErrorMessage(e, 'settings.loadFailed'))
    } finally {
      if (!disposed) pageLoading.value = false
    }
  }

  onMounted(async () => {
    // 同步注册 beforeunload：避免异步加载期间卸载导致监听器永久泄漏
    window.addEventListener('beforeunload', onBeforeUnload)
    await loadAllSettings()
  })

  onUnmounted(() => {
    disposed = true
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
    loadFailed,
    /** 重新加载全局设置（失败重试入口） */
    reload: loadAllSettings,
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
