import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'
import type { AiFormState } from '../lib/settings-form'

const { toastSpy, confirmMock, api } = vi.hoisted(() => ({
  toastSpy: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    show: vi.fn(),
  },
  confirmMock: {
    confirm: vi.fn(async () => true),
  },
  api: {
    saveGlobalSettings: vi.fn(),
    saveTelegramConfig: vi.fn(),
    resetTelegramConfig: vi.fn(),
    saveAIConfig: vi.fn(),
    testAIConnection: vi.fn(),
    runDeviceKeepalive: vi.fn(),
    testBotNotification: vi.fn(),
  },
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
}))
vi.mock('../composables/useConfirm', () => ({
  useConfirm: () => confirmMock,
}))
vi.mock('../lib/api', () => api)

import { useSettingsSave } from '../composables/useSettingsSave'
import { useAuthStore } from '../stores/auth'

describe('useSettingsSave', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.confirm.mockResolvedValue(true)
    useAuthStore().setToken('tok')
  })

  function setup(over?: {
    tg?: { api_id: string; api_hash: string }
    ai?: Partial<AiFormState>
    aiConfigLoaded?: boolean
  }) {
    const markSectionClean = vi.fn()
    const afterBotTokenSaved = vi.fn()
    const afterWebdavSettingsSaved = vi.fn()
    const loadBackupStatus = vi.fn(async () => {})
    const aiRef = ref<AiFormState>({
      provider: 'openai',
      cloudflare_account_id: '',
      cloudflare_account_id_masked: null,
      base_url: '',
      model: '',
      api_key: '',
      fallback_providers: [],
      ...(over?.ai || {}),
    })
    const save = useSettingsSave({
      tgConfig: ref(over?.tg || { api_id: '', api_hash: '' }),
      aiConfig: aiRef,
      aiKeyDecryptFailed: ref(false),
      aiConfigLoaded: ref(over?.aiConfigLoaded ?? true),
      buildGeneralPayload: () => ({ general: 1 }),
      buildBotPayload: () => ({ bot: 1 }),
      buildAdvancedPayload: () => ({ adv: 1 }),
      buildAiRuntimePayload: () => ({ ai_rt: 1 }),
      buildBackupPayload: () => ({ backup: 1 }),
      markSectionClean,
      afterBotTokenSaved,
      afterWebdavSettingsSaved,
      loadBackupStatus,
    })
    return {
      save,
      ai: aiRef,
      markSectionClean,
      afterBotTokenSaved,
      afterWebdavSettingsSaved,
      loadBackupStatus,
    }
  }

  it('saveSettings no-ops without token', async () => {
    useAuthStore().clearToken()
    const { save } = setup()
    await save.saveSettings()
    expect(api.saveGlobalSettings).not.toHaveBeenCalled()
  })

  it('saveSettings success marks general clean', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { save, markSectionClean } = setup()
    await save.saveSettings()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { general: 1 })
    expect(markSectionClean).toHaveBeenCalledWith('general')
    expect(toastSpy.success).toHaveBeenCalled()
    expect(save.loading.value).toBe(false)
  })

  it('saveSettings failure notifies error', async () => {
    api.saveGlobalSettings.mockRejectedValue(new Error('fail'))
    const { save } = setup()
    await save.saveSettings()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('saveBotSettings runs afterBotTokenSaved', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { save, afterBotTokenSaved, markSectionClean } = setup()
    await save.saveBotSettings()
    expect(afterBotTokenSaved).toHaveBeenCalled()
    expect(markSectionClean).toHaveBeenCalledWith('bot')
  })

  it('saveAdvancedSettings reloads backup status', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { save, loadBackupStatus, afterWebdavSettingsSaved } = setup()
    await save.saveAdvancedSettings()
    expect(afterWebdavSettingsSaved).toHaveBeenCalled()
    expect(loadBackupStatus).toHaveBeenCalledWith('tok')
  })

  it('saveAllSettings saves global and optional tg/ai', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveTelegramConfig.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    const { save, markSectionClean } = setup({
      tg: { api_id: '1', api_hash: 'h' },
      ai: { base_url: 'http://x', model: 'm', api_key: 'k', fallback_providers: [] },
    })
    await save.saveAllSettings()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith(
      'tok',
      expect.objectContaining({
        general: 1,
        bot: 1,
        adv: 1,
        ai_rt: 1,
      }),
    )
    expect(api.saveTelegramConfig).toHaveBeenCalled()
    expect(api.saveAIConfig).toHaveBeenCalled()
    expect(markSectionClean).toHaveBeenCalledWith('general')
    expect(markSectionClean).toHaveBeenCalledWith('tg')
    expect(markSectionClean).toHaveBeenCalledWith('ai')
    expect(markSectionClean).toHaveBeenCalledWith('runtime')
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('saveAllSettings reports partial tg failure', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveTelegramConfig.mockRejectedValue(new Error('tg'))
    const { save } = setup({
      tg: { api_id: '1', api_hash: 'h' },
    })
    await save.saveAllSettings()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('saveAllSettings saves tg when only one field is filled', async () => {
    // 回归：原 AND 守卫导致只填一半时静默不保存、输入丢失仍提示"全部已保存"
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveTelegramConfig.mockResolvedValue({})
    const { save, markSectionClean } = setup({
      tg: { api_id: '1', api_hash: '' },
    })
    await save.saveAllSettings()
    expect(api.saveTelegramConfig).toHaveBeenCalledWith(
      'tok',
      expect.objectContaining({ api_id: '1', api_hash: '' }),
    )
    expect(markSectionClean).toHaveBeenCalledWith('tg')
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('saveAllSettings skips tg save when both fields empty', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { save } = setup({
      tg: { api_id: '', api_hash: '' },
    })
    await save.saveAllSettings()
    expect(api.saveTelegramConfig).not.toHaveBeenCalled()
  })

  it('resetTgConfig aborts when confirm false', async () => {
    confirmMock.confirm.mockResolvedValueOnce(false)
    const { save } = setup({ tg: { api_id: '1', api_hash: 'h' } })
    await save.resetTgConfig()
    expect(api.resetTelegramConfig).not.toHaveBeenCalled()
  })

  it('resetTgConfig clears fields', async () => {
    api.resetTelegramConfig.mockResolvedValue({})
    const tg = ref({ api_id: '1', api_hash: 'h' })
    const save = useSettingsSave({
      tgConfig: tg,
      aiConfig: ref({ base_url: '', model: '', api_key: '', fallback_providers: [] }),
      aiKeyDecryptFailed: ref(false),
      buildGeneralPayload: () => ({}),
      buildBotPayload: () => ({}),
      buildAdvancedPayload: () => ({}),
      buildAiRuntimePayload: () => ({}),
      buildBackupPayload: () => ({}),
      markSectionClean: vi.fn(),
      afterBotTokenSaved: vi.fn(),
      afterWebdavSettingsSaved: vi.fn(),
      loadBackupStatus: vi.fn(async () => {}),
    })
    await save.resetTgConfig()
    expect(tg.value.api_id).toBe('')
    expect(tg.value.api_hash).toBe('')
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('testBot routes success/failure messages', async () => {
    api.testBotNotification.mockResolvedValue({ success: true, message: 'ok' })
    const { save } = setup()
    await save.testBot()
    expect(toastSpy.success).toHaveBeenCalledWith('ok')

    api.testBotNotification.mockResolvedValue({ success: false, message: 'bad' })
    await save.testBot()
    expect(toastSpy.error).toHaveBeenCalledWith('bad')
  })

  it('runKeepaliveNow formats result', async () => {
    api.runDeviceKeepalive.mockResolvedValue({ kept_alive: 2, checked: 3, failed: 1 })
    const { save } = setup()
    await save.runKeepaliveNow()
    expect(toastSpy.success).toHaveBeenCalled()
    expect(String(toastSpy.success.mock.calls[0][0])).toContain('2')
  })

  it('saveAiConfig writes only AI config and leaves runtime section untouched', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    const ai = ref({ base_url: 'u', model: 'm', api_key: 'secret', fallback_providers: [] })
    const aiKeyDecryptFailed = ref(true)
    const markSectionClean = vi.fn()
    const save = useSettingsSave({
      tgConfig: ref({ api_id: '', api_hash: '' }),
      aiConfig: ai,
      aiKeyDecryptFailed,
      buildGeneralPayload: () => ({}),
      buildBotPayload: () => ({}),
      buildAdvancedPayload: () => ({}),
      buildAiRuntimePayload: () => ({ rt: 1 }),
      buildBackupPayload: () => ({}),
      markSectionClean,
      afterBotTokenSaved: vi.fn(),
      afterWebdavSettingsSaved: vi.fn(),
      loadBackupStatus: vi.fn(async () => {}),
    })
    await save.saveAiConfig()
    expect(api.saveGlobalSettings).not.toHaveBeenCalled()
    expect(api.saveAIConfig).toHaveBeenCalled()
    expect(ai.value.api_key).toBe('')
    expect(aiKeyDecryptFailed.value).toBe(false)
    expect(markSectionClean).toHaveBeenCalledWith('ai')
    expect(markSectionClean).not.toHaveBeenCalledWith('runtime')
  })

  it('saveAiConfig forwards fallback providers when AI config was loaded', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    const { save } = setup({
      ai: {
        base_url: 'u',
        model: 'm',
        api_key: '',
        fallback_providers: [
          { base_url: 'https://fb.example.com/v1', model: 'm2', api_key: '', api_key_masked: 'sk-****' },
        ],
      },
      aiConfigLoaded: true,
    })
    await save.saveAiConfig()
    expect(api.saveAIConfig).toHaveBeenCalledWith('tok', {
      provider: 'openai',
      cloudflare_account_id: undefined,
      base_url: 'u',
      model: 'm',
      api_key: undefined,
      fallback_providers: [
        // 留空的 api_key 不发，由后端沿用已保存密文
        { base_url: 'https://fb.example.com/v1', model: 'm2', api_key: undefined },
      ],
    })
  })

  it('saveAiConfig omits fallback providers when AI config was not loaded', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    api.saveAIConfig.mockClear()
    const { save } = setup({ aiConfigLoaded: false })
    await save.saveAiConfig()
    expect(api.saveAIConfig).toHaveBeenCalledWith('tok', {
      provider: 'openai',
      cloudflare_account_id: undefined,
      base_url: undefined,
      model: undefined,
      api_key: undefined,
      // fallback_providers 字段必须缺失，避免空数组清空服务端已保存密钥
      fallback_providers: undefined,
    })
  })
  it('saveAiConfig forwards provider and cloudflare_account_id', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    const { save, ai } = setup({
      ai: {
        provider: 'cloudflare',
        cloudflare_account_id: '0123456789abcdef0123456789abcdef',
        base_url: '',
        model: '@cf/meta/llama-3.2-11b-vision-instruct',
        api_key: 'cf-new-token',
        fallback_providers: [],
      },
      aiConfigLoaded: true,
    })
    await save.saveAiConfig()
    expect(api.saveAIConfig).toHaveBeenCalledWith('tok', expect.objectContaining({
      provider: 'cloudflare',
      cloudflare_account_id: '0123456789abcdef0123456789abcdef',
      model: '@cf/meta/llama-3.2-11b-vision-instruct',
      api_key: 'cf-new-token',
    }))
    expect(ai.value.cloudflare_account_id).toBe('')
    expect(ai.value.cloudflare_account_id_masked).toBe('0123************************cdef')
    expect(ai.value.api_key).toBe('')
    expect(ai.value.api_key_masked).toBe('cf-n****oken')
  })

  it('saveAiRuntime success submits runtime payload and marks runtime clean', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { save, markSectionClean } = setup()
    await save.saveAiRuntime()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { ai_rt: 1 })
    expect(markSectionClean).toHaveBeenCalledWith('runtime')
    expect(toastSpy.success).toHaveBeenCalled()
    expect(toastSpy.error).not.toHaveBeenCalled()
  })

  it('saveAiRuntime failure reports error and does not mark runtime clean', async () => {
    api.saveGlobalSettings.mockRejectedValue(new Error('boom'))
    const { save, markSectionClean } = setup()
    await save.saveAiRuntime()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { ai_rt: 1 })
    expect(markSectionClean).not.toHaveBeenCalledWith('runtime')
    expect(toastSpy.error).toHaveBeenCalled()
    expect(toastSpy.success).not.toHaveBeenCalled()
  })
})
