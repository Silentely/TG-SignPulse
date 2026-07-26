import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  flushPromises,
  mockI18nPassthrough,
  mountComposable,
} from './composable-test-utils'

const toastSpy = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  show: vi.fn(),
}))
const confirmMock = vi.hoisted(() => ({
  confirm: vi.fn(async () => true),
}))

const routeLeaveGuard = vi.hoisted(() => ({
  handler: null as null | (() => boolean | Promise<boolean>),
}))

const api = vi.hoisted(() => ({
  getGlobalSettings: vi.fn(),
  getTelegramConfig: vi.fn(),
  getAIConfig: vi.fn(),
  getRuntimeStatus: vi.fn(),
  getMemoryStats: vi.fn(),
  // save/backup/version deps used via nested composables
  saveGlobalSettings: vi.fn(),
  saveTelegramConfig: vi.fn(),
  resetTelegramConfig: vi.fn(),
  saveAIConfig: vi.fn(),
  testAIConnection: vi.fn(),
  runDeviceKeepalive: vi.fn(),
  testBotNotification: vi.fn(),
  getBackupStatus: vi.fn(),
  exportAllConfigs: vi.fn(),
  importAllConfigs: vi.fn(),
  importConfigPreview: vi.fn(),
  exportBackupArchive: vi.fn(),
  testWebdavBackup: vi.fn(),
  listWebdavBackupFiles: vi.fn(),
  downloadWebdavBackup: vi.fn(),
  getAppVersion: vi.fn(),
  checkAppVersion: vi.fn(),
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
vi.mock('vue-router', () => ({
  onBeforeRouteLeave: (fn: () => boolean | Promise<boolean>) => {
    routeLeaveGuard.handler = fn
  },
  useRoute: () => ({ query: {}, name: 'settings' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('../lib/api', () => api)
vi.mock('../lib/version-utils', () => ({
  fetchGithubLatestRelease: vi.fn(),
  friendlyGithubError: vi.fn((e: unknown) => String(e)),
  isUpdateAvailable: vi.fn(() => false),
  loadCachedUpdateCheck: vi.fn(() => null),
  safeHttpUrl: vi.fn((u: string | null) => u),
  saveCachedUpdateCheck: vi.fn(),
}))

import { useSettingsPage } from '../composables/useSettingsPage'
import { useAuthStore } from '../stores/auth'

describe('useSettingsPage (mount + dirty)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeLeaveGuard.handler = null
    confirmMock.confirm.mockResolvedValue(true)
    useAuthStore().setToken('tok')

    api.getGlobalSettings.mockResolvedValue({
      sign_interval: 45,
      log_retention_days: 14,
      telegram_bot_token_set: true,
      webdav_password_set: true,
      webdav_url: 'https://dav.example.com',
      webdav_username: 'u',
      timezone: 'UTC',
      telegram_bot_message_thread_id: 9,
    })
    api.getTelegramConfig.mockResolvedValue({
      is_custom: true,
      api_id: '123',
      api_hash: 'hash',
    })
    api.getAIConfig.mockResolvedValue({
      has_config: true,
      base_url: 'https://ai',
      model: 'm1',
      api_key_decrypt_failed: false,
    })
    api.getBackupStatus.mockResolvedValue({ last: 'ok' })
    api.getRuntimeStatus.mockResolvedValue({ uptime: 1 })
    api.getMemoryStats.mockResolvedValue({ rss: 1 })
    api.getAppVersion.mockResolvedValue({
      version: '1.0.0',
      update_check_enabled: false,
    })
  })

  it('onMounted loads settings/tg/ai and marks clean', async () => {
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => {
      expect(result.pageLoading.value).toBe(false)
    })
    await flushPromises(10)

    expect(result.settings.value.checkInterval).toBe('45')
    expect(result.settings.value.logDays).toBe(14)
    expect(result.settings.value.timezone).toBe('UTC')
    expect(result.settings.value.botThreadId).toBe('9')
    expect(result.botTokenSet.value).toBe(true)
    expect(result.webdavPasswordSet.value).toBe(true)
    expect(result.tgConfig.value.api_id).toBe('123')
    expect(result.aiConfig.value.model).toBe('m1')
    expect(result.runtimeStatus.value).toEqual({ uptime: 1 })
    expect(result.memoryStats.value).toEqual({ rss: 1 })
    expect(result.backupStatus.value).toEqual({ last: 'ok' })
    expect(result.isDirty.value).toBe(false)
    expect(result.appVersion.value?.version).toBe('1.0.0')
    unmount()
  })

  it('without token skips load', async () => {
    useAuthStore().clearToken()
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await flushPromises(10)
    expect(result.pageLoading.value).toBe(false)
    expect(api.getGlobalSettings).not.toHaveBeenCalled()
    unmount()
  })

  it('isDirty tracks field edits and dirtyLabels', async () => {
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))

    expect(result.isDirty.value).toBe(false)
    result.settings.value.proxy = 'socks5://x'
    expect(result.isDirty.value).toBe(true)
    expect(result.dirtyLabels.value.length).toBeGreaterThan(0)
    unmount()
  })

  it('toggleReveal flips secret visibility flags', async () => {
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    expect(result.revealSecrets.value.botToken).toBe(false)
    result.toggleReveal('botToken')
    expect(result.revealSecrets.value.botToken).toBe(true)
    result.toggleReveal('botToken')
    expect(result.revealSecrets.value.botToken).toBe(false)
    unmount()
  })

  it('beforeunload is blocked when dirty', async () => {
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    result.settings.value.proxy = 'x'
    const ev = new Event('beforeunload') as BeforeUnloadEvent
    Object.defineProperty(ev, 'returnValue', { writable: true, value: '' })
    const prevent = vi.spyOn(ev, 'preventDefault')
    window.dispatchEvent(ev)
    expect(prevent).toHaveBeenCalled()
    unmount()
  })

  it('route leave confirms when dirty', async () => {
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    expect(routeLeaveGuard.handler).toBeTruthy()

    // clean → allow
    await expect(routeLeaveGuard.handler!()).resolves.toBe(true)

    result.settings.value.proxy = 'dirty'
    confirmMock.confirm.mockResolvedValueOnce(false)
    await expect(routeLeaveGuard.handler!()).resolves.toBe(false)
    expect(confirmMock.confirm).toHaveBeenCalled()

    confirmMock.confirm.mockResolvedValueOnce(true)
    await expect(routeLeaveGuard.handler!()).resolves.toBe(true)
    unmount()
  })

  it('load failure toasts error', async () => {
    api.getGlobalSettings.mockRejectedValue(new Error('boom'))
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    expect(toastSpy.error).toHaveBeenCalled()
    unmount()
  })

  it('exposes save handlers from nested composables', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    const { result, unmount } = mountComposable(() => useSettingsPage())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    await result.saveSettings()
    expect(api.saveGlobalSettings).toHaveBeenCalled()
    expect(result.isDirty.value).toBe(false)
    unmount()
  })
})
