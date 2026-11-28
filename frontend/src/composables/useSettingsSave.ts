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
import { withToken } from '../lib/api/core'
import type { AiFormState, SettingsSection, TgFormState } from '../lib/settings-form'
import { resolveApiErrorMessage } from '../lib/notify'
import { devLog } from '../lib/devLog'
import { setPanelTimezone } from '../lib/datetime'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'

const maskSecret = (raw: string) => {
  const trimmed = raw.trim()
  return trimmed.length > 8
    ? trimmed.slice(0, 4) + '*'.repeat(Math.max(trimmed.length - 8, 0)) + trimmed.slice(-4)
    : '****'
}

export function useSettingsSave(options: {
  tgConfig: Ref<TgFormState>
  /** 全局 API Hash 是否已保存（GET 只返回脱敏值） */
  tgHasApiHash: Ref<boolean>
  tgApiHashMasked: Ref<string>
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
  afterTgSaved: () => void
  afterTgReset: () => void
  loadBackupStatus: (token: string) => Promise<void>
  /** 服务端 AI 配置是否已成功加载；未加载时不得用空列表覆盖已保存的备用节点 */
  aiConfigLoaded?: Ref<boolean>
  /** JEV 区块是否存在未保存改动，以及对应的全量保存钩子 */
  jevDirty?: Ref<boolean>
  saveJev?: () => Promise<boolean>
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
  const aiRuntimeLoading = ref(false)
  const botTestLoading = ref(false)
  const keepaliveLoading = ref(false)

  const hasPrimaryOrFallbackAiInput = () => {
    const ai = options.aiConfig.value
    const hasPrimary = !!(
      ai.provider === 'cloudflare'
        ? (ai.cloudflare_account_id || ai.api_key || ai.model)
        : (ai.base_url || ai.model || ai.api_key)
    )
    const hasFallback = (ai.fallback_providers || []).some(
      (p) => (p.base_url || '').trim() || (p.api_key || '').trim() || (p.model || '').trim(),
    )
    return hasPrimary || hasFallback
  }

  const submitAiConfig = async (token: string) => {
    const ai = options.aiConfig.value
    // 仅当服务端 AI 配置已成功加载时才提交备用节点，避免用空数组清空已保存的密钥
    const fallbackPayload =
      options.aiConfigLoaded?.value === false
        ? undefined
        : (ai.fallback_providers || [])
            // 无 base_url 且无 api_key 的空行不提交
            .filter((p) => (p.base_url || '').trim() || (p.api_key || '').trim())
            .map((p) => ({
              id: p.id,
              base_url: p.base_url || undefined,
              model: p.model || undefined,
              // 留空表示沿用已保存密钥，不发送该字段
              api_key: p.api_key || undefined,
            }))

    await saveAIConfig(token, {
      provider: ai.provider || 'openai',
      cloudflare_account_id: ai.cloudflare_account_id?.trim() || undefined,
      base_url:
        ai.provider === 'cloudflare'
          ? undefined
          : (ai.base_url || undefined),
      model: ai.model || undefined,
      api_key: ai.api_key || undefined,
      fallback_providers: fallbackPayload,
    })

    if (ai.cloudflare_account_id) {
      ai.cloudflare_account_id_masked = maskSecret(ai.cloudflare_account_id)
      ai.cloudflare_account_id = ''
    }
    if (ai.api_key) {
      options.aiKeyDecryptFailed.value = false
      ai.api_key_masked = maskSecret(ai.api_key)
    }
    ai.api_key = ''
    for (const p of ai.fallback_providers || []) {
      if (p.api_key) {
        p.api_key_masked = maskSecret(p.api_key)
        p.api_key = ''
      }
    }
  }

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
          ...options.buildAiRuntimePayload(),
        })
        // 保存成功后立即同步面板展示时区，Dashboard/Logs 等页时间格式跟随
        setPanelTimezone(String(options.buildGeneralPayload().timezone || ''))
        options.afterWebdavSettingsSaved()
        options.afterBotTokenSaved()
        options.markSectionClean('general')
        options.markSectionClean('bot')
        options.markSectionClean('advanced')
        options.markSectionClean('runtime')
        try {
          await options.loadBackupStatus(token)
        } catch {
          /* ignore */
        }
        // 任一字段有值即保存（与独立保存一致）：原来用 AND 守卫，
        // 只填一个字段时静默走 else 不保存，用户输入丢失且仍提示"全部已保存"
        if (options.tgConfig.value.api_id || options.tgConfig.value.api_hash) {
          try {
            await saveTelegramConfig(token, {
              api_id: options.tgConfig.value.api_id,
              api_hash: options.tgConfig.value.api_hash,
            })
            options.afterTgSaved()
            options.markSectionClean('tg')
          } catch (e: unknown) {
            partial.push(t('settings.tgApi'))
            devLog.error('saveAll tg failed', e)
          }
        } else {
          options.markSectionClean('tg')
        }
        const hasAllAiInput = hasPrimaryOrFallbackAiInput()
        if (hasAllAiInput) {
          try {
            await submitAiConfig(token)
            options.markSectionClean('ai')
          } catch (e: unknown) {
            partial.push(t('settings.aiConfig'))
            devLog.error('saveAll ai failed', e)
          }
        } else {
          options.markSectionClean('ai')
        }
        if (options.jevDirty?.value && options.saveJev) {
          try {
            const ok = await options.saveJev()
            if (!ok) partial.push(t('settings.jevConfig'))
          } catch (e: unknown) {
            partial.push(t('settings.jevConfig'))
            devLog.error('saveAll jev failed', e)
          }
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
    return withToken(async (token) => {
      tgLoading.value = true
      try {
        await saveTelegramConfig(token, {
          api_id: options.tgConfig.value.api_id,
          api_hash: options.tgConfig.value.api_hash,
        })
        options.afterTgSaved()
        options.markSectionClean('tg')
        notifySuccess(t('settings.tgConfigSaved'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        tgLoading.value = false
      }
    })
  }

  const resetTgConfig = async () => {
    return withToken(async (token) => {
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
        options.afterTgReset()
        options.markSectionClean('tg')
        notifySuccess(t('settings.resetSuccess'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.resetFailed'))
      } finally {
        tgLoading.value = false
      }
    })
  }

  const saveAiConfig = async () => {
    return withToken(async (token) => {
      aiLoading.value = true
      try {
        const hasAiInput = hasPrimaryOrFallbackAiInput()
        try {
          await submitAiConfig(token)
        } catch (e: unknown) {
          if (hasAiInput) throw e
          devLog.error('saveAi model skipped (no key yet)', e)
        }
        options.markSectionClean('ai')
        notifySuccess(t('settings.aiConfigSaved'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        aiLoading.value = false
      }
    })
  }

  const saveAiRuntime = async () => {
    return withToken(async (token) => {
      aiRuntimeLoading.value = true
      try {
        await saveGlobalSettings(token, options.buildAiRuntimePayload())
        options.markSectionClean('runtime')
        notifySuccess(t('settings.saveSuccess'))
      } catch (e: unknown) {
        notifyError(resolveApiErrorMessage(e, 'settings.saveFailed'))
      } finally {
        aiRuntimeLoading.value = false
      }
    })
  }

  const testAi = async () => {
    return withToken(async (token) => {
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
    })
  }

  return {
    loading,
    botLoading,
    advancedLoading,
    saveAllLoading,
    tgLoading,
    aiLoading,
    aiRuntimeLoading,
    botTestLoading,
    keepaliveLoading,
    saveSettings,
    runKeepaliveNow,
    saveBotSettings,
    saveAdvancedSettings,
    saveAllSettings,
    saveAiRuntime,
    testBot,
    saveTgConfig,
    resetTgConfig,
    saveAiConfig,
    testAi,
  }
}
