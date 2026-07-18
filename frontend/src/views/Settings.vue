<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Settings2, KeyRound, Bot, Sparkles, Database, Info, RefreshCw, ExternalLink, Eye, EyeOff } from 'lucide-vue-next'
import {
  getGlobalSettings,
  saveGlobalSettings,
  getTelegramConfig,
  saveTelegramConfig,
  resetTelegramConfig,
  getAIConfig,
  saveAIConfig,
  testAIConnection,
  exportAllConfigs,
  importAllConfigs,
  importConfigPreview,
  runDeviceKeepalive,
  getBackupStatus,
  exportBackupArchive,
  getRuntimeStatus,
  getAppVersion,
  checkAppVersion,
  testBotNotification,
  getMemoryStats,
} from '../lib/api'
import type { BackupStatus, RuntimeStatus, AppVersionInfo, UpdateCheckInfo, MemoryStatsResponse } from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import CustomSelect from '../components/CustomSelect.vue'
import { useAuthStore } from '../stores/auth'
import { getLocalizedErrorMessage } from '../lib/types'
import { devLog } from '../lib/devLog'
import {
  fetchGithubLatestRelease,
  isUpdateAvailable,
  loadCachedUpdateCheck,
  safeHttpUrl,
  saveCachedUpdateCheck,
} from '../lib/version-utils'
import {
  buildAdvancedPayload as buildAdvancedPayloadOf,
  buildBotPayload as buildBotPayloadOf,
  buildGeneralPayload as buildGeneralPayloadOf,
  dirtySectionLabels,
  isAnySectionDirty,
  snapAllSections,
  type SettingsSection,
} from '../lib/settings-form'

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
const memoryStats = ref<MemoryStatsResponse | null>(null)
const advancedLoading = ref(false)
const botTestLoading = ref(false)
const pageLoading = ref(true)
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
    advanced: t('settings.advanced'),
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

const formatMemoryRss = () => {
  const stats = memoryStats.value?.stats || {}
  const rssMb = stats.rss_mb ?? stats.rssMb
  if (typeof rssMb === 'number') return `${rssMb.toFixed(1)} MB`
  const rss = stats.rss_bytes ?? stats.rss
  if (typeof rss === 'number') return `${(rss / (1024 * 1024)).toFixed(1)} MB`
  return t('settings.unknownValue')
}

const appVersion = ref<AppVersionInfo | null>(null)
const versionLoading = ref(false)
const checkLoading = ref(false)
const versionBanner = ref<{
  kind: 'update' | 'latest' | 'error' | 'info'
  text: string
  url?: string | null
} | null>(null)

const notifySuccess = (msg: string) => toast.success(msg)
const notifyError = (msg: string) => toast.error(msg)

const shortSha = (sha?: string) => {
  if (!sha) return t('settings.unknownValue')
  return sha.length > 12 ? sha.slice(0, 12) : sha
}

const setUpdateBanner = (
  kind: 'update' | 'latest' | 'error' | 'info',
  text: string,
  url?: string | null,
) => {
  versionBanner.value = { kind, text, url: safeHttpUrl(url ?? null) }
}

const applyClientCache = () => {
  const cached = loadCachedUpdateCheck()
  if (!cached?.update_available || !cached.latest_version) return
  setUpdateBanner(
    'update',
    t('settings.updateAvailable', { version: cached.latest_version }),
    cached.latest_url,
  )
}

const loadVersion = async (token: string) => {
  versionLoading.value = true
  try {
    appVersion.value = await getAppVersion(token)
    applyClientCache()
  } catch (e) {
    devLog.error('Failed to load app version', e)
  } finally {
    versionLoading.value = false
  }
}

const runBrowserFallbackCheck = async (currentVersion: string) => {
  const latest = await fetchGithubLatestRelease()
  const available = isUpdateAvailable(currentVersion, latest.version)
  const safeUrl = safeHttpUrl(latest.url)
  saveCachedUpdateCheck({
    latest_version: latest.version,
    latest_url: safeUrl,
    update_available: available,
    checked_at: new Date().toISOString(),
    error: null,
  })
  if (available) {
    setUpdateBanner(
      'update',
      t('settings.updateAvailable', { version: latest.version }),
      safeUrl,
    )
  } else {
    setUpdateBanner('latest', t('settings.alreadyLatest'))
  }
}

const showFromRemote = (uc: UpdateCheckInfo) => {
  if (uc.error && !uc.latest_version) {
    setUpdateBanner(
      'error',
      t('settings.updateCheckFailed', { error: uc.error }),
    )
    return
  }
  const safeUrl = safeHttpUrl(uc.latest_url)
  if (uc.update_available && uc.latest_version) {
    saveCachedUpdateCheck({
      latest_version: uc.latest_version,
      latest_url: safeUrl,
      update_available: true,
      checked_at: uc.checked_at || new Date().toISOString(),
      error: null,
    })
    setUpdateBanner(
      'update',
      t('settings.updateAvailable', { version: uc.latest_version }),
      safeUrl,
    )
    return
  }
  saveCachedUpdateCheck({
    latest_version: uc.latest_version,
    latest_url: safeUrl,
    update_available: false,
    checked_at: uc.checked_at || new Date().toISOString(),
    error: null,
  })
  setUpdateBanner('latest', t('settings.alreadyLatest'))
}

const handleCheckUpdate = async (force = true) => {
  const token = authStore.token || ''
  if (!token || !appVersion.value) return
  checkLoading.value = true
  versionBanner.value = null
  const current = appVersion.value.version

  try {
    if (appVersion.value.update_check_enabled) {
      try {
        const res = await checkAppVersion(token, force)
        appVersion.value = {
          version: res.version,
          git_sha: res.git_sha,
          git_branch: res.git_branch,
          build_time: res.build_time,
          app_name: res.app_name,
          python: res.python,
          update_check_enabled: res.update_check_enabled,
        }
        if (res.update_check.error && !res.update_check.latest_version) {
          try {
            await runBrowserFallbackCheck(res.version)
          } catch (browserErr) {
            const msg = browserErr instanceof Error ? browserErr.message : String(browserErr)
            setUpdateBanner(
              'error',
              t('settings.updateCheckFailed', {
                error: res.update_check.error || msg,
              }),
            )
          }
          return
        }
        showFromRemote(res.update_check)
        return
      } catch {
        try {
          await runBrowserFallbackCheck(current)
        } catch (browserErr) {
          const msg = browserErr instanceof Error ? browserErr.message : String(browserErr)
          setUpdateBanner(
            'error',
            t('settings.updateCheckFailed', { error: msg }),
          )
        }
        return
      }
    }
    // 服务端关闭远程检查：浏览器直连 GitHub
    setUpdateBanner('info', t('settings.updateCheckDisabled'))
    try {
      await runBrowserFallbackCheck(current)
    } catch (browserErr) {
      const msg = browserErr instanceof Error ? browserErr.message : String(browserErr)
      setUpdateBanner(
        'error',
        t('settings.updateCheckFailed', { error: msg }),
      )
    }
  } finally {
    checkLoading.value = false
  }
}

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
    settings.value.botTaskSuccess = res.telegram_bot_task_success_enabled || false
    settings.value.quietEnabled = res.telegram_bot_quiet_hours_enabled || false
    settings.value.quietStart = res.telegram_bot_quiet_hours_start || '23:00'
    settings.value.quietEnd = res.telegram_bot_quiet_hours_end || '07:00'
    settings.value.botToken = res.telegram_bot_token || ''
    settings.value.botChatId = res.telegram_bot_chat_id || ''
    settings.value.botThreadId = res.telegram_bot_message_thread_id ? String(res.telegram_bot_message_thread_id) : ''
    settings.value.timezone = res.timezone || 'Asia/Hong_Kong'
    settings.value.execTimeout = res.sign_task_execution_timeout ?? ''
    settings.value.accountCooldown = res.sign_task_account_cooldown ?? ''
    settings.value.flowRetry = res.sign_task_flow_retry_attempts ?? ''
    settings.value.historyMaxAge = res.sign_task_history_max_age_days ?? ''
    settings.value.aiVisionTimeout = res.ai_vision_timeout ?? ''
    settings.value.aiVisionRetry = res.ai_vision_retry_attempts ?? ''
    settings.value.autoBackupEnabled = res.auto_backup_enabled || false
    settings.value.autoBackupInterval = res.auto_backup_interval_hours || 24
    settings.value.autoBackupKeep = res.auto_backup_keep || 3

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
    try {
      memoryStats.value = await getMemoryStats(token)
    } catch (e) {
      devLog.error('Failed to load memory stats', e)
    }
    await loadVersion(token)
    markAllClean()
    window.addEventListener('beforeunload', onBeforeUnload)
  } catch (e) {
    devLog.error('Failed to load settings', e)
    notifyError(getLocalizedErrorMessage(e, t, t('settings.loadFailed')))
  } finally {
    pageLoading.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', onBeforeUnload)
})

const buildGeneralPayload = () => buildGeneralPayloadOf(settings.value)
const buildBotPayload = () => buildBotPayloadOf(settings.value)
const buildAdvancedPayload = () => buildAdvancedPayloadOf(settings.value)

const saveSettings = async () => {
  const token = authStore.token || ''
  if (!token) return

  loading.value = true
  try {
    await saveGlobalSettings(token, buildGeneralPayload())
    markSectionClean('general')
    notifySuccess(t('settings.saveSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    loading.value = false
  }
}

const botLoading = ref(false)
const keepaliveLoading = ref(false)
const saveAllLoading = ref(false)

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
    await saveGlobalSettings(token, buildBotPayload())
    markSectionClean('bot')
    notifySuccess(t('settings.saveSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    botLoading.value = false
  }
}

const saveAdvancedSettings = async () => {
  const token = authStore.token || ''
  if (!token) return
  advancedLoading.value = true
  try {
    await saveGlobalSettings(token, buildAdvancedPayload())
    markSectionClean('advanced')
    notifySuccess(t('settings.saveSuccess'))
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    advancedLoading.value = false
  }
}

/** 一次提交全局设置 + 可选 TG/AI，解决分块保存遗漏 */
const saveAllSettings = async () => {
  const token = authStore.token || ''
  if (!token) return
  saveAllLoading.value = true
  const partial: string[] = []
  try {
    await saveGlobalSettings(token, {
      ...buildGeneralPayload(),
      ...buildBotPayload(),
      ...buildAdvancedPayload(),
    })
    markSectionClean('general')
    markSectionClean('bot')
    markSectionClean('advanced')
    if (tgConfig.value.api_id && tgConfig.value.api_hash) {
      try {
        await saveTelegramConfig(token, {
          api_id: tgConfig.value.api_id,
          api_hash: tgConfig.value.api_hash,
        })
        markSectionClean('tg')
      } catch (e: unknown) {
        partial.push(t('settings.tgApi'))
        devLog.error('saveAll tg failed', e)
      }
    } else {
      markSectionClean('tg')
    }
    if (aiConfig.value.base_url || aiConfig.value.model || aiConfig.value.api_key) {
      try {
        await saveAIConfig(token, {
          base_url: aiConfig.value.base_url || undefined,
          model: aiConfig.value.model || undefined,
          api_key: aiConfig.value.api_key || undefined,
        })
        aiConfig.value.api_key = ''
        markSectionClean('ai')
      } catch (e: unknown) {
        partial.push(t('settings.aiConfig'))
        devLog.error('saveAll ai failed', e)
      }
    } else {
      markSectionClean('ai')
    }
    if (partial.length) {
      notifyError(`${t('settings.saveAllPartial')}: ${partial.join(', ')}`)
    } else {
      notifySuccess(t('settings.saveAllSuccess'))
    }
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
  } finally {
    saveAllLoading.value = false
  }
}

const testBot = async () => {
  const token = authStore.token || ''
  if (!token) return
  botTestLoading.value = true
  try {
    const res = await testBotNotification(token)
    if (res.success) notifySuccess(res.message)
    else notifyError(res.message)
  } catch (e: unknown) {
    notifyError(getLocalizedErrorMessage(e, t, t('settings.testFailed')))
  } finally {
    botTestLoading.value = false
  }
}

const saveTgConfig = async () => {
  const token = authStore.token || ''
  tgLoading.value = true
  try {
    await saveTelegramConfig(token, { api_id: tgConfig.value.api_id, api_hash: tgConfig.value.api_hash })
    markSectionClean('tg')
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
    markSectionClean('tg')
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
    aiConfig.value.api_key = ''
    markSectionClean('ai')
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
      const preview = await importConfigPreview(token, jsonStr)
      if (preview.errors?.length) {
        notifyError(`${t('settings.importFailed')}: ${preview.errors.slice(0, 2).join('; ')}`)
        return
      }
      const conflictHint = preview.conflicts?.length
        ? `\n${t('settings.importConflicts')}: ${preview.conflicts.slice(0, 5).join(', ')}${preview.conflicts.length > 5 ? '…' : ''}`
        : ''
      const ok = await confirm({
        title: t('settings.importPreviewTitle'),
        message: `signs=${preview.signs_count}, monitors=${preview.monitors_count}, settings=${(preview.settings_keys || []).join(',') || '-'}${conflictHint}`,
        confirmText: t('common.continue'),
        danger: Boolean(preview.conflicts?.length),
      })
      if (!ok) return
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
    <div
      v-if="isDirty && !pageLoading"
      class="sticky top-0 z-20 mb-4 flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-200 shadow-sm"
      role="status"
    >
      <div class="min-w-0">
        <div>{{ t('settings.unsavedBanner') }}</div>
        <div v-if="dirtyLabels.length" class="mt-0.5 text-[10px] opacity-90">
          {{ t('settings.dirtySections') }}: {{ dirtyLabels.join(' · ') }}
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-primary !px-3 !py-1.5 !text-xs shrink-0"
        :disabled="saveAllLoading || loading || botLoading || advancedLoading || tgLoading || aiLoading"
        @click="saveAllSettings"
      >
        {{ saveAllLoading ? t('settings.saving') : t('settings.saveAll') }}
      </button>
    </div>
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
            <div class="space-y-1.5">
              <label class="ui-label">{{ t('settings.signInterval') }}</label>
              <input v-model="settings.checkInterval" type="number" min="0" max="3600" :placeholder="t('settings.signIntervalPlaceholder')" class="ui-input">
              <p class="text-[10px] text-gray-500">{{ t('settings.signIntervalHint') }}</p>
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
              <div class="relative">
                <input v-model="tgConfig.api_id" :type="revealSecrets.tgApiId ? 'text' : 'password'" class="ui-input pr-10" autocomplete="off">
                <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="revealSecrets.tgApiId ? t('settings.hideSecret') : t('settings.showSecret')" @click="revealSecrets.tgApiId = !revealSecrets.tgApiId">
                  <EyeOff v-if="revealSecrets.tgApiId" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
                </button>
              </div>
            </div>
            <div class="space-y-1.5">
              <label class="ui-label">API Hash</label>
              <div class="relative">
                <input v-model="tgConfig.api_hash" :type="revealSecrets.tgApiHash ? 'text' : 'password'" class="ui-input pr-10">
                <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="revealSecrets.tgApiHash ? t('settings.hideSecret') : t('settings.showSecret')" @click="revealSecrets.tgApiHash = !revealSecrets.tgApiHash">
                  <EyeOff v-if="revealSecrets.tgApiHash" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
                </button>
              </div>
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
              <div class="relative">
                <input v-model="aiConfig.api_key" :type="revealSecrets.aiKey ? 'text' : 'password'" placeholder="sk-..." class="ui-input pr-10">
                <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="revealSecrets.aiKey ? t('settings.hideSecret') : t('settings.showSecret')" @click="revealSecrets.aiKey = !revealSecrets.aiKey">
                  <EyeOff v-if="revealSecrets.aiKey" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
                </button>
              </div>
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
              <div class="relative">
                <input v-model="settings.botToken" :type="revealSecrets.botToken ? 'text' : 'password'" placeholder="123456:ABC-DEF..." class="ui-input pr-10">
                <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="revealSecrets.botToken ? t('settings.hideSecret') : t('settings.showSecret')" @click="revealSecrets.botToken = !revealSecrets.botToken">
                  <EyeOff v-if="revealSecrets.botToken" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
                </button>
              </div>
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
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="settings.botTaskSuccess" type="checkbox" class="w-4 h-4 accent-sky-500 bg-gray-100 border-gray-300 rounded focus:ring-0 dark:bg-gray-800 dark:border-gray-600">
                <span class="text-sm text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors">{{ t('settings.taskSuccessNotify') }}</span>
              </label>
            </div>
            <div class="p-3 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/60 space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <label class="text-xs text-gray-600 dark:text-gray-300 block">{{ t('settings.quietHours') }}</label>
                  <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.quietHoursDesc') }}</p>
                </div>
                <button
                  type="button"
                  class="ui-switch"
                  role="switch"
                  :aria-checked="settings.quietEnabled"
                  :class="settings.quietEnabled ? 'ui-switch-on' : ''"
                  @click="settings.quietEnabled = !settings.quietEnabled"
                >
                  <span class="ui-switch-knob" />
                </button>
              </div>
              <div class="grid grid-cols-2 gap-2" v-if="settings.quietEnabled">
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.quietStart') }}</label>
                  <input v-model="settings.quietStart" type="text" placeholder="23:00" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.quietEnd') }}</label>
                  <input v-model="settings.quietEnd" type="text" placeholder="07:00" class="ui-input" />
                </div>
              </div>
            </div>
            <div class="pt-2 flex flex-col sm:flex-row gap-2">
              <button type="button" class="ui-btn-primary flex-1 py-2.5" :disabled="botLoading" @click="saveBotSettings">{{ botLoading ? t('settings.saving') : t('settings.saveChanges') }}</button>
              <button type="button" class="ui-btn-secondary flex-1 py-2.5" :disabled="botTestLoading" @click="testBot">{{ botTestLoading ? t('settings.testing') : t('settings.testBot') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- 数据管理（左列） -->
      <div class="flex flex-col gap-6">
        <section class="ui-card p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start gap-3">
            <span class="ui-section-icon" aria-hidden="true"><Database class="w-3.5 h-3.5" /></span>
            <div>
              <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.dataManagement') }}</h2>
              <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.dataManagementDesc') }}</p>
            </div>
          </div>

          <!-- 配置迁移 JSON -->
          <div class="space-y-3 mb-6">
            <div>
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.configMigrateTitle') }}</h3>
              <p class="text-xs text-gray-500 mt-1 leading-relaxed">{{ t('settings.configMigrateDesc') }}</p>
            </div>
            <div class="flex flex-col sm:flex-row gap-3">
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
          <div class="pt-5 border-t border-gray-200 dark:border-gray-800/60 space-y-3">
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
            <div class="p-3 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/60 space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <label class="text-xs text-gray-600 dark:text-gray-300 block">{{ t('settings.autoBackup') }}</label>
                  <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.autoBackupDesc') }}</p>
                </div>
                <button
                  type="button"
                  class="ui-switch"
                  role="switch"
                  :aria-checked="settings.autoBackupEnabled"
                  :class="settings.autoBackupEnabled ? 'ui-switch-on' : ''"
                  @click="settings.autoBackupEnabled = !settings.autoBackupEnabled"
                >
                  <span class="ui-switch-knob" />
                </button>
              </div>
              <div class="grid grid-cols-2 gap-2">
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.autoBackupInterval') }}</label>
                  <input v-model.number="settings.autoBackupInterval" type="number" min="1" max="168" class="ui-input" :disabled="!settings.autoBackupEnabled" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.autoBackupKeep') }}</label>
                  <input v-model.number="settings.autoBackupKeep" type="number" min="1" max="30" class="ui-input" :disabled="!settings.autoBackupEnabled" />
                </div>
              </div>
              <button type="button" class="ui-btn-secondary w-full !py-2 !text-xs" :disabled="advancedLoading" @click="saveAdvancedSettings">
                {{ advancedLoading ? t('settings.saving') : t('settings.saveAdvanced') }}
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
          </div>
        </section>
      </div>

      <!-- 关于 / 版本（右列） -->
      <div class="flex flex-col gap-6">
        <section class="ui-card p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start justify-between gap-3">
            <div class="flex items-start gap-3 min-w-0">
              <span class="ui-section-icon" aria-hidden="true"><Info class="w-3.5 h-3.5" /></span>
              <div class="min-w-0">
                <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.aboutTitle') }}</h2>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.aboutDesc') }}</p>
              </div>
            </div>
            <button
              type="button"
              class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5"
              :disabled="checkLoading || versionLoading || !appVersion"
              @click="handleCheckUpdate(true)"
            >
              <RefreshCw class="w-3.5 h-3.5" :class="checkLoading ? 'animate-spin' : ''" />
              {{ checkLoading ? t('settings.checkingUpdate') : t('settings.checkUpdate') }}
            </button>
          </div>

          <div class="space-y-4">
            <div
              v-if="appVersion"
              class="p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-1.5 font-mono"
            >
              <div class="text-gray-600 dark:text-gray-400">
                <span class="text-gray-500">{{ t('settings.currentVersion') }}:</span>
                <span class="ml-1 text-gray-900 dark:text-gray-100 font-medium">v{{ appVersion.version }}</span>
              </div>
              <div class="text-gray-600 dark:text-gray-400">
                <span class="text-gray-500">{{ t('settings.gitSha') }}:</span>
                <span class="ml-1">{{ shortSha(appVersion.git_sha) }}</span>
              </div>
              <div class="text-gray-600 dark:text-gray-400">
                <span class="text-gray-500">{{ t('settings.gitBranch') }}:</span>
                <span class="ml-1">{{ appVersion.git_branch || t('settings.unknownValue') }}</span>
              </div>
              <div class="text-gray-600 dark:text-gray-400">
                <span class="text-gray-500">{{ t('settings.buildTime') }}:</span>
                <span class="ml-1">{{ appVersion.build_time || t('settings.unknownValue') }}</span>
              </div>
              <div class="text-gray-600 dark:text-gray-400">
                <span class="text-gray-500">{{ t('settings.pythonRuntime') }}:</span>
                <span class="ml-1">{{ appVersion.python }}</span>
              </div>
            </div>
            <p v-else-if="versionLoading" class="text-xs text-gray-500">{{ t('settings.processing') }}</p>

            <!-- 运行时状态 -->
            <div v-if="runtimeStatus" class="p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-1.5">
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
              <div v-if="memoryStats?.available" class="text-gray-600 dark:text-gray-400">
                {{ t('settings.memoryRss') }}: {{ formatMemoryRss() }}
              </div>
            </div>

            <!-- 高级执行 / AI -->
            <div class="p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-3">
              <div>
                <div class="font-medium text-gray-700 dark:text-gray-300">{{ t('settings.advanced') }}</div>
                <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.advancedDesc') }}</p>
                <p class="text-[10px] text-gray-500">{{ t('settings.emptyAdvancedHint') }}</p>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.execTimeout') }}</label>
                  <input v-model="settings.execTimeout" type="number" min="30" max="3600" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.accountCooldown') }}</label>
                  <input v-model="settings.accountCooldown" type="number" min="0" max="600" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.flowRetry') }}</label>
                  <input v-model="settings.flowRetry" type="number" min="1" max="10" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.historyMaxAge') }}</label>
                  <input v-model="settings.historyMaxAge" type="number" min="1" max="90" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.aiVisionTimeout') }}</label>
                  <input v-model="settings.aiVisionTimeout" type="number" min="3" max="120" class="ui-input" />
                </div>
                <div class="space-y-1">
                  <label class="text-[10px] text-gray-500">{{ t('settings.aiVisionRetry') }}</label>
                  <input v-model="settings.aiVisionRetry" type="number" min="1" max="8" class="ui-input" />
                </div>
              </div>
              <button type="button" class="ui-btn-primary w-full !py-2" :disabled="advancedLoading" @click="saveAdvancedSettings">
                {{ advancedLoading ? t('settings.saving') : t('settings.saveAdvanced') }}
              </button>
            </div>

            <div
              v-if="versionBanner"
              class="text-xs rounded-md px-3 py-2 border"
              :class="{
                'border-sky-300/80 bg-sky-50 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100': versionBanner.kind === 'update' || versionBanner.kind === 'info',
                'border-emerald-300/80 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100': versionBanner.kind === 'latest',
                'border-amber-300/80 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100': versionBanner.kind === 'error',
              }"
            >
              <div class="font-medium">{{ versionBanner.text }}</div>
              <p v-if="versionBanner.kind === 'update'" class="mt-1 opacity-90">{{ t('settings.updateAvailableHint') }}</p>
              <p v-if="versionBanner.kind === 'update'" class="mt-1 opacity-80 font-mono">{{ t('settings.upgradeDockerHint') }}</p>
              <a
                v-if="versionBanner.url"
                :href="versionBanner.url"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 mt-2 text-sky-700 dark:text-sky-300 underline-offset-2 hover:underline"
              >
                {{ t('settings.openRelease') }}
                <ExternalLink class="w-3 h-3" />
              </a>
            </div>
          </div>
        </section>
      </div>

    </div>
  </div>
</template>
