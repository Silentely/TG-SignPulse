/**
 * 系统设置页业务逻辑：加载/保存/脏检查/备份/版本检查。
 * Settings.vue 仅负责布局与子组件接线。
 */
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
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
  testWebdavBackup,
  listWebdavBackupFiles,
  downloadWebdavBackup,
  getRuntimeStatus,
  getAppVersion,
  checkAppVersion,
  testBotNotification,
  getMemoryStats,
} from '../lib/api'
import type { BackupStatus, RuntimeStatus, AppVersionInfo, UpdateCheckInfo, MemoryStatsResponse, WebDavRemoteFile } from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useAuthStore } from '../stores/auth'
import { getLocalizedErrorMessage } from '../lib/types'
import { devLog } from '../lib/devLog'
import {
  fetchGithubLatestRelease,
  friendlyGithubError,
  isUpdateAvailable,
  loadCachedUpdateCheck,
  safeHttpUrl,
  saveCachedUpdateCheck,
} from '../lib/version-utils'
import {
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

export function useSettingsPage() {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const authStore = useAuthStore()

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
              // 优先展示服务端友好文案（已含限流提示），浏览器错误再压短
              const msg =
                res.update_check.error ||
                friendlyGithubError(browserErr)
              setUpdateBanner(
                'error',
                t('settings.updateCheckFailed', { error: msg }),
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
            setUpdateBanner(
              'error',
              t('settings.updateCheckFailed', {
                error: friendlyGithubError(browserErr),
              }),
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
        setUpdateBanner(
          'error',
          t('settings.updateCheckFailed', {
            error: friendlyGithubError(browserErr),
          }),
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
      // Token 不回传明文
      settings.value.botToken = ''
      botTokenSet.value = !!res.telegram_bot_token_set
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
      settings.value.webdavUrl = res.webdav_url || ''
      settings.value.webdavUsername = res.webdav_username || ''
      // 密码不回传明文：仅根据 password_set 展示「已保存」提示
      settings.value.webdavPassword = ''
      webdavPasswordSet.value = !!res.webdav_password_set
      settings.value.webdavRemoteDir = res.webdav_remote_dir || 'tg-signpulse-backups'

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
  const buildAiRuntimePayload = () => buildAiRuntimePayloadOf(settings.value)
  const buildBackupPayload = () => buildBackupPayloadOf(settings.value)

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
      afterBotTokenSaved()
      markSectionClean('bot')
      notifySuccess(t('settings.saveSuccess'))
    } catch (e: unknown) {
      notifyError(getLocalizedErrorMessage(e, t, t('settings.saveFailed')))
    } finally {
      botLoading.value = false
    }
  }

  /** 数据管理：仅保存备份 / WebDAV 字段 */
  const saveAdvancedSettings = async () => {
    const token = authStore.token || ''
    if (!token) return
    advancedLoading.value = true
    try {
      await saveGlobalSettings(token, buildBackupPayload())
      afterWebdavSettingsSaved()
      markSectionClean('advanced')
      notifySuccess(t('settings.saveSuccess'))
      try {
        backupStatus.value = await getBackupStatus(token)
      } catch {
        /* ignore */
      }
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
      afterWebdavSettingsSaved()
      afterBotTokenSaved()
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

  /** 统一保存 AI 模型配置 + 高级执行/视觉运行时参数 */
  const saveAiConfig = async () => {
    const token = authStore.token || ''
    aiLoading.value = true
    try {
      // 运行时参数写入全局 settings（与模型配置同一按钮）
      await saveGlobalSettings(token, buildAiRuntimePayload())

      const hasAiInput = !!(
        aiConfig.value.base_url ||
        aiConfig.value.model ||
        aiConfig.value.api_key
      )
      try {
        await saveAIConfig(token, {
          base_url: aiConfig.value.base_url || undefined,
          model: aiConfig.value.model || undefined,
          api_key: aiConfig.value.api_key || undefined,
        })
        // 用户重填 Key 后清除解密失败提示
        if (aiConfig.value.api_key) {
          aiKeyDecryptFailed.value = false
        }
        aiConfig.value.api_key = ''
      } catch (e: unknown) {
        // 仅改运行时且尚未配置 AI Key 时，模型保存失败可忽略
        if (hasAiInput) throw e
        devLog.error('saveAi model skipped (runtime-only or no key yet)', e)
      }

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
      if (res.success) {
        notifySuccess(res.message || t('settings.testSuccess'))
      } else {
        notifyError(res.message || t('settings.testFailed'))
      }
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

  const webdavTestLoading = ref(false)
  const webdavListLoading = ref(false)
  const remoteWebdavFiles = ref<WebDavRemoteFile[]>([])
  const remoteWebdavMessage = ref('')
  /** 服务端是否已保存 WebDAV 密码（GET 不回传明文） */
  const webdavPasswordSet = ref(false)
  /** 服务端是否已保存 Bot Token */
  const botTokenSet = ref(false)
  /** 当前下载的远程文件名 */
  const remoteDownloadName = ref('')

  const validateWebdavForm = (): boolean => {
    if (!settings.value.webdavUrl.trim()) {
      notifyError(t('settings.webdavRequired'))
      return false
    }
    if (!settings.value.webdavUsername.trim()) {
      notifyError(t('settings.webdavUsernameRequired'))
      return false
    }
    if (!settings.value.webdavPassword && !webdavPasswordSet.value) {
      notifyError(t('settings.webdavPasswordRequired'))
      return false
    }
    return true
  }

  /** 保存 advanced 后：若本次提交了新密码则标记已保存并清空输入框 */
  const afterWebdavSettingsSaved = () => {
    if (settings.value.webdavPassword) {
      webdavPasswordSet.value = true
      settings.value.webdavPassword = ''
    }
  }

  const afterBotTokenSaved = () => {
    if (settings.value.botToken) {
      botTokenSet.value = true
      settings.value.botToken = ''
    }
  }

  const handleListRemoteBackups = async () => {
    const token = authStore.token || ''
    if (!settings.value.webdavUrl.trim()) {
      notifyError(t('settings.webdavRequired'))
      return
    }
    webdavListLoading.value = true
    remoteWebdavMessage.value = ''
    try {
      // 先落盘当前表单，确保列表用最新凭据
      await saveGlobalSettings(token, buildBackupPayload())
      afterWebdavSettingsSaved()
      markSectionClean('advanced')
      const res = await listWebdavBackupFiles(token)
      if (!res.success) {
        remoteWebdavFiles.value = []
        remoteWebdavMessage.value = res.message || t('settings.webdavListFailed')
        notifyError(remoteWebdavMessage.value)
        return
      }
      remoteWebdavFiles.value = res.files || []
      remoteWebdavMessage.value =
        res.message ||
        (remoteWebdavFiles.value.length
          ? t('settings.webdavListOk')
          : t('settings.webdavListEmpty'))
    } catch (e: unknown) {
      remoteWebdavFiles.value = []
      notifyError(getLocalizedErrorMessage(e, t, t('settings.webdavListFailed')))
    } finally {
      webdavListLoading.value = false
    }
  }

  const handleDownloadRemoteBackup = async (name: string) => {
    const token = authStore.token || ''
    if (!name) return
    remoteDownloadName.value = name
    try {
      const res = await downloadWebdavBackup(token, name)
      notifySuccess(`${t('settings.webdavDownloadOk')}: ${res.filename}`)
    } catch (e: unknown) {
      notifyError(getLocalizedErrorMessage(e, t, t('settings.webdavDownloadFailed')))
    } finally {
      remoteDownloadName.value = ''
    }
  }

  const handleBackupExport = async () => {
    const token = authStore.token || ''
    if (!validateWebdavForm()) return
    backupLoading.value = true
    try {
      // 服务端读已落盘配置：上传前先保存 WebDAV/备份相关字段
      await saveGlobalSettings(token, buildBackupPayload())
      afterWebdavSettingsSaved()
      markSectionClean('advanced')
      const res = await exportBackupArchive(token)
      if (res.mode === 'webdav') {
        notifySuccess(
          res.filename
            ? `${t('settings.backupWebdavSuccess')}: ${res.filename}`
            : t('settings.backupWebdavSuccess'),
        )
      } else {
        // 服务端未读到 WebDAV（配置异常）时的兼容回退
        notifySuccess(t('settings.backupExportSuccess'))
      }
      try {
        backupStatus.value = await getBackupStatus(token)
      } catch {
        /* ignore refresh errors */
      }
    } catch (e: unknown) {
      notifyError(getLocalizedErrorMessage(e, t, t('settings.backupExportFailed')))
    } finally {
      backupLoading.value = false
    }
  }

  const handleWebdavTest = async () => {
    const token = authStore.token || ''
    if (!validateWebdavForm()) return
    // 先保存当前 WebDAV 配置再测
    advancedLoading.value = true
    webdavTestLoading.value = true
    try {
      await saveGlobalSettings(token, buildBackupPayload())
      afterWebdavSettingsSaved()
      markSectionClean('advanced')
      const res = await testWebdavBackup(token)
      if (res.success) notifySuccess(res.message || t('settings.webdavTestOk'))
      else notifyError(res.message || t('settings.webdavTestFailed'))
    } catch (e: unknown) {
      notifyError(getLocalizedErrorMessage(e, t, t('settings.webdavTestFailed')))
    } finally {
      advancedLoading.value = false
      webdavTestLoading.value = false
    }
  }

  const handleImportFile = async (file: File) => {
    const token = authStore.token || ''
    const reader = new FileReader()
    reader.onload = async (ev) => {
      const jsonStr = ev.target?.result as string
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
      }
    }
    reader.readAsText(file)
  }

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
