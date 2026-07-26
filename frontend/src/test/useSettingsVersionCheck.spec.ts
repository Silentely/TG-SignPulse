import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mockI18nPassthrough } from './composable-test-utils'

const api = vi.hoisted(() => ({
  getAppVersion: vi.fn(),
  checkAppVersion: vi.fn(),
}))

const versionUtils = vi.hoisted(() => ({
  fetchGithubLatestRelease: vi.fn(),
  friendlyGithubError: vi.fn((e: unknown) => String(e)),
  isUpdateAvailable: vi.fn(),
  loadCachedUpdateCheck: vi.fn(() => null),
  safeHttpUrl: vi.fn((u: string | null) => u),
  saveCachedUpdateCheck: vi.fn(),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../lib/api', () => api)
vi.mock('../lib/version-utils', () => versionUtils)

import { useSettingsVersionCheck } from '../composables/useSettingsVersionCheck'
import { useAuthStore } from '../stores/auth'

describe('useSettingsVersionCheck', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore().setToken('tok')
    versionUtils.loadCachedUpdateCheck.mockReturnValue(null)
    versionUtils.safeHttpUrl.mockImplementation((u: string | null) => u)
  })

  it('loadVersion sets appVersion and applies cache banner', async () => {
    api.getAppVersion.mockResolvedValue({
      version: '1.0.0',
      update_check_enabled: true,
    })
    versionUtils.loadCachedUpdateCheck.mockReturnValue({
      update_available: true,
      latest_version: '1.1.0',
      latest_url: 'https://example.com/r',
    })
    const { loadVersion, appVersion, versionBanner, versionLoading } = useSettingsVersionCheck()
    await loadVersion('tok')
    expect(appVersion.value?.version).toBe('1.0.0')
    expect(versionBanner.value?.kind).toBe('update')
    expect(versionLoading.value).toBe(false)
  })

  it('handleCheckUpdate uses server update_check when enabled', async () => {
    api.getAppVersion.mockResolvedValue({
      version: '1.0.0',
      update_check_enabled: true,
    })
    api.checkAppVersion.mockResolvedValue({
      version: '1.0.0',
      git_sha: 'abc',
      git_branch: 'dev',
      build_time: '',
      app_name: 'tg',
      python: '3',
      update_check_enabled: true,
      update_check: {
        update_available: true,
        latest_version: '2.0.0',
        latest_url: 'https://example.com/v2',
        error: null,
      },
    })
    const vc = useSettingsVersionCheck()
    await vc.loadVersion('tok')
    await vc.handleCheckUpdate(true)
    expect(api.checkAppVersion).toHaveBeenCalledWith('tok', true)
    expect(vc.versionBanner.value?.kind).toBe('update')
    expect(versionUtils.saveCachedUpdateCheck).toHaveBeenCalled()
    expect(vc.checkLoading.value).toBe(false)
  })

  it('handleCheckUpdate falls back to browser github when server errors', async () => {
    api.getAppVersion.mockResolvedValue({
      version: '1.0.0',
      update_check_enabled: true,
    })
    api.checkAppVersion.mockRejectedValue(new Error('net'))
    versionUtils.fetchGithubLatestRelease.mockResolvedValue({
      version: '1.2.0',
      url: 'https://github.com/x/y',
    })
    versionUtils.isUpdateAvailable.mockReturnValue(true)
    const vc = useSettingsVersionCheck()
    await vc.loadVersion('tok')
    await vc.handleCheckUpdate()
    expect(versionUtils.fetchGithubLatestRelease).toHaveBeenCalled()
    expect(vc.versionBanner.value?.kind).toBe('update')
  })

  it('handleCheckUpdate no-ops without token or version', async () => {
    useAuthStore().clearToken()
    const vc = useSettingsVersionCheck()
    await vc.handleCheckUpdate()
    expect(api.checkAppVersion).not.toHaveBeenCalled()
  })

  it('handleCheckUpdate shows already latest', async () => {
    api.getAppVersion.mockResolvedValue({
      version: '1.0.0',
      update_check_enabled: true,
    })
    api.checkAppVersion.mockResolvedValue({
      version: '1.0.0',
      git_sha: '',
      git_branch: '',
      build_time: '',
      app_name: '',
      python: '',
      update_check_enabled: true,
      update_check: {
        update_available: false,
        latest_version: '1.0.0',
        latest_url: null,
        error: null,
      },
    })
    const vc = useSettingsVersionCheck()
    await vc.loadVersion('tok')
    await vc.handleCheckUpdate()
    expect(vc.versionBanner.value?.kind).toBe('latest')
  })
})
