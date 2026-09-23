/**
 * 设置页：配置导入导出、WebDAV / 对象存储备份与完整备份。
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
  testS3Backup,
  listS3BackupFiles,
  downloadS3Backup,
  saveGlobalSettings,
  type BackupStatus,
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
  const s3TestLoading = ref(false)
  const s3ListLoading = ref(false)
  const remoteS3Files = ref<RemoteBackupFile[]>([])
  const remoteS3Message = ref('')
  const s3SecretKeySet = ref(false)
  const remoteS3DownloadName = ref('')

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

  /** 对象存储必填项：endpoint / 桶 / Access Key / Secret Key（已保存的密钥可不再填） */
  const validateS3Form = (): boolean => {
    const s = options.settings.value
    if (!s.s3EndpointUrl.trim()) {
      notifyError(t('settings.s3EndpointRequired'))
      return false
    }
    if (!s.s3Bucket.trim()) {
      notifyError(t('settings.s3BucketRequired'))
      return false
    }
    if (!s.s3AccessKey.trim()) {
      notifyError(t('settings.s3AccessKeyRequired'))
      return false
    }
    if (!s.s3SecretKey && !s3SecretKeySet.value) {
      notifyError(t('settings.s3SecretKeyRequired'))
      return false
    }
    return true
  }

  const afterS3SettingsSaved = () => {
    if (options.settings.value.s3SecretKey) {
      s3SecretKeySet.value = true
      options.settings.value.s3SecretKey = ''
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

  const handleListS3RemoteBackups = async () => {
    const token = getAuthToken()
    if (!validateS3Form()) return
    s3ListLoading.value = true
    remoteS3Message.value = ''
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterS3SettingsSaved()
      options.markSectionClean('advanced')
      const res = await listS3BackupFiles(token)
      if (!res.success) {
        remoteS3Files.value = []
        remoteS3Message.value = res.message || t('settings.s3ListFailed')
        notifyError(remoteS3Message.value)
        return
      }
      remoteS3Files.value = res.files || []
      remoteS3Message.value =
        res.message ||
        (remoteS3Files.value.length
          ? t('settings.s3ListOk')
          : t('settings.s3ListEmpty'))
    } catch (e: unknown) {
      remoteS3Files.value = []
      notifyError(resolveApiErrorMessage(e, 'settings.s3ListFailed'))
    } finally {
      s3ListLoading.value = false
    }
  }

  const handleDownloadS3RemoteBackup = async (name: string) => {
    const token = getAuthToken()
    if (!name) return
    remoteS3DownloadName.value = name
    try {
      const res = await downloadS3Backup(token, name)
      notifySuccess(`${t('settings.s3DownloadOk')}: ${res.filename}`)
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.s3DownloadFailed'))
    } finally {
      remoteS3DownloadName.value = ''
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

  const handleBackupExport = async () => {
    const token = getAuthToken()
    if (!validateWebdavForm()) return
    backupLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
      const res = await exportBackupArchive(token)
      if (res.mode === 'download') {
        notifySuccess(t('settings.backupExportSuccess'))
      } else {
        // 服务端按「WebDAV → 对象存储」优先级返回 mode，据此提示落点
        const label =
          res.mode === 's3'
            ? t('settings.backupS3Success')
            : t('settings.backupWebdavSuccess')
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

  const handleWebdavTest = async () => {
    const token = getAuthToken()
    if (!validateWebdavForm()) return
    webdavTestLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterWebdavSettingsSaved()
      options.markSectionClean('advanced')
      const res = await testWebdavBackup(token)
      if (res.success) notifySuccess(res.message || t('settings.webdavTestOk'))
      else notifyError(res.message || t('settings.webdavTestFailed'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.webdavTestFailed'))
    } finally {
      webdavTestLoading.value = false
    }
  }

  const handleS3Test = async () => {
    const token = getAuthToken()
    if (!validateS3Form()) return
    s3TestLoading.value = true
    try {
      await saveGlobalSettings(token, options.buildBackupPayload())
      afterS3SettingsSaved()
      options.markSectionClean('advanced')
      const res = await testS3Backup(token)
      if (res.success) notifySuccess(res.message || t('settings.s3TestOk'))
      else notifyError(res.message || t('settings.s3TestFailed'))
    } catch (e: unknown) {
      notifyError(resolveApiErrorMessage(e, 'settings.s3TestFailed'))
    } finally {
      s3TestLoading.value = false
    }
  }

  const handleImportFile = async (file: File) => {
    const token = getAuthToken()
    const reader = new FileReader()
    // 读取失败（权限/文件被删/损坏）必须给用户反馈，否则点击导入毫无反应
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

  const loadBackupStatus = async (token: string) => {
    backupStatus.value = await getBackupStatus(token)
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
    s3TestLoading,
    s3ListLoading,
    remoteS3Files,
    remoteS3Message,
    s3SecretKeySet,
    remoteS3DownloadName,
    afterWebdavSettingsSaved,
    afterS3SettingsSaved,
    handleExport,
    handleListRemoteBackups,
    handleDownloadRemoteBackup,
    handleListS3RemoteBackups,
    handleDownloadS3RemoteBackup,
    handleBackupExport,
    handleWebdavTest,
    handleS3Test,
    handleImportFile,
    loadBackupStatus,
  }
}
