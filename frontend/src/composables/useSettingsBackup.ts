/**
 * 设置页：配置导入导出、WebDAV 备份与完整备份。
 */
import { ref, type Ref } from 'vue'
import {
  exportAllConfigs,
  importAllConfigs,
  importConfigPreview,
  getBackupStatus,
  exportBackupArchive,
  importBackupArchive,
  testWebdavBackup,
  listWebdavBackupFiles,
  downloadWebdavBackup,
  saveGlobalSettings,
  type BackupStatus,
  type BackupArchiveOptions,
  type RemoteBackupFile,
} from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import { downloadBlob } from '../lib/download'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { resolveApiErrorMessage } from '../lib/notify'
import type { SettingsFormState } from '../lib/settings-form'

export function useSettingsBackup(options: {
  settings: Ref<SettingsFormState>
  buildBackupPayload: () => Record<string, unknown>
  markSectionClean: (section: 'advanced') => void
}) {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()

  const notifySuccess = (msg: string) => toast.success(msg)
  const notifyError = (msg: string) => toast.error(msg)

  const dataLoading = ref(false)
  const backupLoading = ref(false)
  const backupStatus = ref<BackupStatus | null>(null)
  const webdavTestLoading = ref(false)
  const webdavListLoading = ref(false)
  const remoteWebdavFiles = ref<RemoteBackupFile[]>([])
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
    const token = getAuthToken()
    dataLoading.value = true
    try {
      const jsonStr = await exportAllConfigs(token)
      const blob = new Blob([jsonStr], { type: 'application/json' })
      downloadBlob(blob, `tg-signpulse-export-${new Date().toISOString().split('T')[0]}.json`)
      notifySuccess(t('settings.exportSuccess'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.exportFailed'))
    } finally {
      dataLoading.value = false
    }
  }

  const handleListRemoteBackups = async () => {
    const token = getAuthToken()
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
      notifyError(resolveApiErrorMessage(e, 'settings.webdavListFailed'))
    } finally {
      webdavListLoading.value = false
    }
  }

  const handleDownloadRemoteBackup = async (name: string) => {
    const token = getAuthToken()
    if (!name) return
    remoteDownloadName.value = name
    try {
      const res = await downloadWebdavBackup(token, name)
      notifySuccess(`${t('settings.webdavDownloadOk')}: ${res.filename}`)
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.webdavDownloadFailed'))
    } finally {
      remoteDownloadName.value = ''
    }
  }

  const handleBackupExport = async (
    target: 'auto' | 'webdav' | 'download' = 'webdav',
    archiveOpts?: BackupArchiveOptions,
  ) => {
    const token = getAuthToken()
    if (target === 'download') {
      // 直接下载不需要校验 WebDAV
    } else {
      if (!validateWebdavForm()) return
    }

    backupLoading.value = true
    try {
      if (target !== 'download') {
        await saveGlobalSettings(token, options.buildBackupPayload())
        afterWebdavSettingsSaved()
        options.markSectionClean('advanced')
      }
      const res = await exportBackupArchive(token, target, archiveOpts)
      if (res.mode === 'download') {
        notifySuccess(t('settings.backupExportSuccess'))
      } else {
        const label = t('settings.backupWebdavSuccess')
        notifySuccess(res.filename ? `${label}: ${res.filename}` : label)
      }
      try {
        backupStatus.value = await getBackupStatus(token)
      } catch {
        /* ignore refresh errors */
      }
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.backupExportFailed'))
    } finally {
      backupLoading.value = false
    }
  }

  const handleDirectDownloadBackup = (archiveOpts?: BackupArchiveOptions) =>
    handleBackupExport('download', archiveOpts)

  const handleArchiveImport = async (file: File, password?: string) => {
    const token = getAuthToken()
    backupLoading.value = true
    try {
      const res = await importBackupArchive(token, file, password)
      notifySuccess(res.message || t('settings.backupImportSuccess'))
      try {
        backupStatus.value = await getBackupStatus(token)
      } catch {
        /* ignore refresh errors */
      }
      return res
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.backupImportFailed'))
      throw e
    } finally {
      backupLoading.value = false
    }
  }

  const loadBackupStatus = async (token: string) => {
    backupStatus.value = await getBackupStatus(token)
  }

  const handleWebdavTest = async () => {
    const token = getAuthToken()
    if (!validateWebdavForm()) return
    webdavTestLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
      const res = await testWebdavBackup(token)
      if (res.success) {
        notifySuccess(res.message || t('settings.webdavTestOk'))
        try {
          await loadBackupStatus(token)
        } catch {
          // non-blocking
        }
      } else {
        notifyError(res.message || t('settings.webdavTestFailed'))
      }
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.webdavTestFailed'))
    } finally {
      webdavTestLoading.value = false
    }
  }

  const handleImportFile = async (file: File) => {
    const token = getAuthToken()
    const reader = new FileReader()
    reader.onerror = () => {
      notifyError(resolveApiErrorMessage(reader.error, 'settings.importFailed'))
    }
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
        notifyError(resolveApiErrorMessage(err, 'settings.importFailed'))
      } finally {
        dataLoading.value = false
      }
    }
    reader.readAsText(file)
  }

  return {
    dataLoading,
    backupLoading,
    backupStatus,
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
    handleDirectDownloadBackup,
    handleArchiveImport,
    handleWebdavTest,
    handleImportFile,
    loadBackupStatus,
  }
}
