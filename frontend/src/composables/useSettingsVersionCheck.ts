/**
 * 设置页：应用版本加载与更新检查。
 */
import { ref } from 'vue'
import {
  getAppVersion,
  checkAppVersion,
  type AppVersionInfo,
  type UpdateCheckInfo,
} from '../lib/api'
import { useI18n } from './useI18n'
import { useAuthStore } from '../stores/auth'
import { devLog } from '../lib/devLog'
import {
  fetchGithubLatestRelease,
  friendlyGithubError,
  isUpdateAvailable,
  loadCachedUpdateCheck,
  safeHttpUrl,
  saveCachedUpdateCheck,
} from '../lib/version-utils'

export type VersionBanner = {
  kind: 'update' | 'latest' | 'error' | 'info'
  text: string
  url?: string | null
}

export function useSettingsVersionCheck() {
  const { t } = useI18n()
  const authStore = useAuthStore()

  const appVersion = ref<AppVersionInfo | null>(null)
  const versionLoading = ref(false)
  const checkLoading = ref(false)
  const versionBanner = ref<VersionBanner | null>(null)

  const setUpdateBanner = (
    kind: VersionBanner['kind'],
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

  return {
    appVersion,
    versionLoading,
    checkLoading,
    versionBanner,
    loadVersion,
    handleCheckUpdate,
  }
}
