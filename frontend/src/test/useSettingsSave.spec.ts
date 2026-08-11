import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'

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
    ai?: { base_url: string; model: string; api_key: string }
  }) {
    const markSectionClean = vi.fn()
    const afterBotTokenSaved = vi.fn()
    const afterWebdavSettingsSaved = vi.fn()
    const loadBackupStatus = vi.fn(async () => {})
    const save = useSettingsSave({
      tgConfig: ref(over?.tg || { api_id: '', api_hash: '' }),
      aiConfig: ref(over?.ai || { base_url: '', model: '', api_key: '' }),
      aiKeyDecryptFailed: ref(false),
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
    return { save, markSectionClean, afterBotTokenSaved, afterWebdavSettingsSaved, loadBackupStatus }
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
      ai: { base_url: 'http://x', model: 'm', api_key: 'k' },
    })
    await save.saveAllSettings()
    expect(api.saveGlobalSettings).toHaveBeenCalled()
    expect(api.saveTelegramConfig).toHaveBeenCalled()
    expect(api.saveAIConfig).toHaveBeenCalled()
    expect(markSectionClean).toHaveBeenCalledWith('general')
    expect(markSectionClean).toHaveBeenCalledWith('tg')
    expect(markSectionClean).toHaveBeenCalledWith('ai')
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
      aiConfig: ref({ base_url: '', model: '', api_key: '' }),
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

  it('saveAiConfig writes runtime then model', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.saveAIConfig.mockResolvedValue({})
    const ai = ref({ base_url: 'u', model: 'm', api_key: 'secret' })
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
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { rt: 1 })
    expect(api.saveAIConfig).toHaveBeenCalled()
    expect(ai.value.api_key).toBe('')
    expect(aiKeyDecryptFailed.value).toBe(false)
    expect(markSectionClean).toHaveBeenCalledWith('ai')
  })
})
