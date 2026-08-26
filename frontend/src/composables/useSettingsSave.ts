/**
 * 设置页：分块保存 / 全量保存 / TG·AI 保存与测试。
 */
import { ref, type Ref } from 'vue'
import {
  saveGlobalSettings,
  saveTelegramConfig,
  resetTelegramConfig,
  saveAIConfig,
  testAIConnection,
  runDeviceKeepalive,
  testBotNotification,
} from '../lib/api'
import { withToken, getAuthToken } from '../lib/api/core'
import type { AiFormState, SettingsSection, TgFormState } from '../lib/settings-form'
import { resolveApiErrorMessage } from '../lib/notify'
import { devLog } from '../lib/devLog'
import { setPanelTimezone } from '../lib/datetime'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'

export function useSettingsSave(options: {
  tgConfig: Ref<TgFormState>
  aiConfig: Ref<AiFormState>
  aiKeyDecryptFailed: Ref<boolean>
  buildGeneralPayload: () => Record<string, unknown>
  buildBotPayload: () => Record<string, unknown>
  buildAdvancedPayload: () => Record<string, unknown>
  buildAiRuntimePayload: () => Record<string, unknown>
  buildBackupPayload: () => Record<string, unknown>
  markSectionClean: (section: SettingsSection) => void
  afterBotTokenSaved: () => void
  afterWebdavSettingsSaved: () => void
  loadBackupStatus: (token: string) => Promise<void>
}) {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const notifySuccess = (msg: string) => toast.success(msg)
  const notifyError = (msg: string) => toast.error(msg)

  const loading = ref(false)
  const botLoading = ref(false)
  const advancedLoading = ref(false)
  const saveAllLoading = ref(false)
  const tgLoading = ref(false)
  const aiLoading = ref(false)
  const botTestLoading = ref(false)
  const keepaliveLoading = ref(false)

  const saveSettings = async () => {
    return withToken(async (token) => {
      loading.value = true
      try {
        await saveGlobalSettings(token, options.buildGeneralPayload())
        // 保存成功后立即同步面板展示时区，Dashboard/Logs 等页时间格式跟随
        setPanelTimezone(String(options.buildGeneralPayload().timezone || ''))
        options.markSectionClean('general')
        notifySuccess(t('settings.saveSuccess'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        loading.value = false
      }
    })
  }

  const runKeepaliveNow = async () => {
    return withToken(async (token) => {
      keepaliveLoading.value = true
      try {
        const res = await runDeviceKeepalive(token)
        // 整句走 i18n 插值：标点与语序交给词条，避免英文界面混入中文全角标点
        notifySuccess(
          t('settings.keepaliveSummary', {
            kept: res.kept_alive,
            checked: res.checked,
            failed: res.failed,
          }),
        )
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.keepaliveFailed'))
      } finally {
        keepaliveLoading.value = false
      }
    })
  }

  const saveBotSettings = async () => {
    return withToken(async (token) => {
      botLoading.value = true
      try {
        await saveGlobalSettings(token, options.buildBotPayload())
        options.afterBotTokenSaved()
        options.markSectionClean('bot')
        notifySuccess(t('settings.saveSuccess'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        botLoading.value = false
      }
    })
  }

  const saveAdvancedSettings = async () => {
    return withToken(async (token) => {
      advancedLoading.value = true
      try {
        await saveGlobalSettings(token, options.buildBackupPayload())
        options.afterWebdavSettingsSaved()
        options.markSectionClean('advanced')
        notifySuccess(t('settings.saveSuccess'))
        try {
          await options.loadBackupStatus(token)
        } catch {
          /* ignore */
        }
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        advancedLoading.value = false
      }
    })
  }

  const saveAllSettings = async () => {
    return withToken(async (token) => {
      saveAllLoading.value = true
      const partial: string[] = []
      try {
        await saveGlobalSettings(token, {
          ...options.buildGeneralPayload(),
          ...options.buildBotPayload(),
          ...options.buildAdvancedPayload(),
        })
        // 保存成功后立即同步面板展示时区，Dashboard/Logs 等页时间格式跟随
        setPanelTimezone(String(options.buildGeneralPayload().timezone || ''))
        options.afterWebdavSettingsSaved()
        options.afterBotTokenSaved()
        options.markSectionClean('general')
        options.markSectionClean('bot')
        options.markSectionClean('advanced')
        // 任一字段有值即保存（与独立保存一致）：原来用 AND 守卫，
        // 只填一个字段时静默走 else 不保存，用户输入丢失且仍提示"全部已保存"
        if (options.tgConfig.value.api_id || options.tgConfig.value.api_hash) {
          try {
            await saveTelegramConfig(token, {
              api_id: options.tgConfig.value.api_id,
              api_hash: options.tgConfig.value.api_hash,
            })
            options.markSectionClean('tg')
          } catch (e: unknown) {
            partial.push(t('settings.tgApi'))
            devLog.error('saveAll tg failed', e)
          }
        } else {
          options.markSectionClean('tg')
        }
        if (
          options.aiConfig.value.base_url ||
          options.aiConfig.value.model ||
          options.aiConfig.value.api_key
        ) {
          try {
            await saveAIConfig(token, {
              base_url: options.aiConfig.value.base_url || undefined,
              model: options.aiConfig.value.model || undefined,
              api_key: options.aiConfig.value.api_key || undefined,
            })
            options.aiConfig.value.api_key = ''
            options.markSectionClean('ai')
          } catch (e: unknown) {
            partial.push(t('settings.aiConfig'))
            devLog.error('saveAll ai failed', e)
          }
        } else {
          options.markSectionClean('ai')
        }
        if (partial.length) {
          notifyError(`${t('settings.saveAllPartial')}: ${partial.join(', ')}`)
        } else {
          notifySuccess(t('settings.saveAllSuccess'))
        }
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        saveAllLoading.value = false
      }
    })
  }

  const testBot = async () => {
    return withToken(async (token) => {
      botTestLoading.value = true
      try {
        const res = await testBotNotification(token)
        if (res.success) notifySuccess(res.message)
        else notifyError(res.message)
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.testFailed'))
      } finally {
        botTestLoading.value = false
      }
    })
  }

  const saveTgConfig = async () => {
    const token = getAuthToken()
    tgLoading.value = true
    try {
      await saveTelegramConfig(token, {
        api_id: options.tgConfig.value.api_id,
        api_hash: options.tgConfig.value.api_hash,
      })
      options.markSectionClean('tg')
      notifySuccess(t('settings.tgConfigSaved'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
    } finally {
      tgLoading.value = false
    }
  }

  const resetTgConfig = async () => {
    const token = getAuthToken()
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
      options.tgConfig.value.api_id = ''
      options.tgConfig.value.api_hash = ''
      options.markSectionClean('tg')
      notifySuccess(t('settings.resetSuccess'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.resetFailed'))
    } finally {
      tgLoading.value = false
    }
  }

  const saveAiConfig = async () => {
    const token = getAuthToken()
    aiLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildAiRuntimePayload())
      const hasAiInput = !!(
        options.aiConfig.value.base_url ||
        options.aiConfig.value.model ||
        options.aiConfig.value.api_key
      )
      try {
        await saveAIConfig(token, {
          base_url: options.aiConfig.value.base_url || undefined,
          model: options.aiConfig.value.model || undefined,
          api_key: options.aiConfig.value.api_key || undefined,
        })
        if (options.aiConfig.value.api_key) {
          options.aiKeyDecryptFailed.value = false
        }
        options.aiConfig.value.api_key = ''
      } catch (e: unknown) {
        if (hasAiInput) throw e
        devLog.error('saveAi model skipped (runtime-only or no key yet)', e)
      }
      options.markSectionClean('ai')
      notifySuccess(t('settings.aiConfigSaved'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
    } finally {
      aiLoading.value = false
    }
  }

  const testAi = async () => {
    const token = getAuthToken()
    aiLoading.value = true
    try {
      const res = await testAIConnection(token)
      if (res.success) {
        notifySuccess(res.message || t('settings.testSuccess'))
      } else {
        notifyError(res.message || t('settings.testFailed'))
      }
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.testFailed'))
    } finally {
      aiLoading.value = false
    }
  }

  return {
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
  }
}
