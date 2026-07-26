/**
 * 设置页：配置导入导出、WebDAV 与完整备份。
 */
import { ref, type Ref } from 'vue'
import {
  exportAllConfigs,
  importAllConfigs,
  importConfigPreview,
  getBackupStatus,
  exportBackupArchive,
  testWebdavBackup,
  listWebdavBackupFiles,
  downloadWebdavBackup,
  saveGlobalSettings,
  type BackupStatus,
  type WebDavRemoteFile,
} from '../lib/api'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { useAuthStore } from '../stores/auth'
import { getLocalizedErrorMessage } from '../lib/types'
import type { SettingsFormState } from '../lib/settings-form'

type Notify = (msg: string) => void

export function useSettingsBackup(options: {
  settings: Ref<SettingsFormState>
  buildBackupPayload: () => Record<string, unknown>
  markSectionClean: (section: 'advanced') => void
  notifySuccess?: Notify
  notifyError?: Notify
}) {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()
  const authStore = useAuthStore()

  const notifySuccess = options.notifySuccess || ((msg: string) => toast.success(msg))
  const notifyError = options.notifyError || ((msg: string) => toast.error(msg))

  const dataLoading = ref(false)
  const backupLoading = ref(false)
  const backupStatus = ref<BackupStatus | null>(null)
  const advancedLoading = ref(false)
  const webdavTestLoading = ref(false)
  const webdavListLoading = ref(false)
  const remoteWebdavFiles = ref<WebDavRemoteFile[]>([])
  const remoteWebdavMessage = ref('')
  const webdavPasswordSet = ref(false)
  const remoteDownloadName = ref('')

  const validateWebdavForm = (): boolean => {
    if (!options.settings.value.webdavUrl.trim()) {
      notifyError(t('settings.webdavRequired'))
      return false
    }
    if (!options.settings.value.webdavUsername.trim()) {
      notifyError(t('settings.webdavUsernameRequired'))
      return false
    }
    if (!options.settings.value.webdavPassword && !webdavPasswordSet.value) {
      notifyError(t('settings.webdavPasswordRequired'))
      return false
    }
    return true
  }

  const afterWebdavSettingsSaved = () => {
    if (options.settings.value.webdavPassword) {
      webdavPasswordSet.value = true
      options.settings.value.webdavPassword = ''
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

  const handleListRemoteBackups = async () => {
    const token = authStore.token || ''
    if (!options.settings.value.webdavUrl.trim()) {
      notifyError(t('settings.webdavRequired'))
      return
    }
    webdavListLoading.value = true
    remoteWebdavMessage.value = ''
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
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
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
      const res = await exportBackupArchive(token)
      if (res.mode === 'webdav') {
        notifySuccess(
          res.filename
            ? `${t('settings.backupWebdavSuccess')}: ${res.filename}`
            : t('settings.backupWebdavSuccess'),
        )
      } else {
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
    advancedLoading.value = true
    webdavTestLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
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

  const loadBackupStatus = async (token: string) => {
    try {
      backupStatus.value = await getBackupStatus(token)
    } catch (e) {
      // 调用方可选记日志
      throw e
    }
  }

  return {
    dataLoading,
    backupLoading,
    backupStatus,
    advancedLoading,
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
  }
}
