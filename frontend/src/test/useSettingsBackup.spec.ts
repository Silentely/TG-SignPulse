import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'
import type { SettingsFormState } from '../lib/settings-form'

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
    exportAllConfigs: vi.fn(),
    importAllConfigs: vi.fn(),
    importConfigPreview: vi.fn(),
    getBackupStatus: vi.fn(),
    exportBackupArchive: vi.fn(),
    testWebdavBackup: vi.fn(),
    listWebdavBackupFiles: vi.fn(),
    downloadWebdavBackup: vi.fn(),
    saveGlobalSettings: vi.fn(),
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

import { useSettingsBackup } from '../composables/useSettingsBackup'
import { useAuthStore } from '../stores/auth'

function baseSettings(over: Partial<SettingsFormState> = {}): SettingsFormState {
  return {
    checkInterval: '',
    logDays: 7,
    dataDir: '',
    proxy: '',
    concurrency: 1,
    deviceKeepaliveEnabled: true,
    deviceKeepaliveIntervalDays: 30,
    botEnabled: false,
    botLoginNotify: false,
    botTaskFailure: false,
    botTaskSuccess: false,
    quietEnabled: false,
    quietStart: '23:00',
    quietEnd: '07:00',
    botToken: '',
    botChatId: '',
    botThreadId: '',
    timezone: 'Asia/Hong_Kong',
    execTimeout: '',
    accountCooldown: '',
    flowRetry: '',
    historyMaxAge: '',
    aiVisionTimeout: '',
    aiVisionRetry: '',
    aiVisionReasoningEffort: '',
    autoBackupEnabled: false,
    autoBackupInterval: 24,
    autoBackupKeep: 3,
    webdavUrl: 'https://dav.example.com',
    webdavUsername: 'user',
    webdavPassword: 'pass',
    webdavRemoteDir: 'tg-signpulse-backups',
    backupTarget: 'auto',
    ...over,
  }
}

describe('useSettingsBackup', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.confirm.mockResolvedValue(true)
    useAuthStore().setToken('tok')
    // blob download stubs
    vi.stubGlobal(
      'URL',
      class {
        static createObjectURL = vi.fn(() => 'blob:url')
        static revokeObjectURL = vi.fn()
      } as unknown as typeof URL,
    )
  })

  function setup(over: Partial<SettingsFormState> = {}) {
    const settings = ref(baseSettings(over))
    const buildBackupPayload = vi.fn(() => ({ backup: 1 }))
    const markSectionClean = vi.fn()
    const backup = useSettingsBackup({
      settings,
      buildBackupPayload,
      markSectionClean,
    })
    return { backup, settings, buildBackupPayload, markSectionClean }
  }

  it('handleExport creates blob download', async () => {
    api.exportAllConfigs.mockResolvedValue('{"a":1}')
    const { backup } = setup()
    await backup.handleExport()
    expect(api.exportAllConfigs).toHaveBeenCalledWith('tok')
    expect(toastSpy.success).toHaveBeenCalledWith('settings.exportSuccess')
    expect(backup.dataLoading.value).toBe(false)
  })

  it('handleExport surfaces error toast', async () => {
    api.exportAllConfigs.mockRejectedValue(new Error('boom'))
    const { backup } = setup()
    await backup.handleExport()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('handleListRemoteBackups validates empty url', async () => {
    const { backup } = setup({ webdavUrl: '' })
    await backup.handleListRemoteBackups()
    expect(api.listWebdavBackupFiles).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalledWith('settings.webdavRequired')
  })

  it('handleListRemoteBackups saves settings then lists files', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.listWebdavBackupFiles.mockResolvedValue({
      success: true,
      files: [{ name: 'b1.tar.gz', size_bytes: 100, mtime: '2026-01-01' }],
    })
    const { backup, markSectionClean } = setup()
    await backup.handleListRemoteBackups()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { backup: 1 })
    expect(markSectionClean).toHaveBeenCalledWith('advanced')
    expect(api.listWebdavBackupFiles).toHaveBeenCalledWith('tok')
    expect(backup.remoteWebdavFiles.value).toHaveLength(1)
  })

  it('handleListRemoteBackups surfaces API failure message', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.listWebdavBackupFiles.mockResolvedValue({
      success: false,
      message: 'forbidden',
    })
    const { backup } = setup()
    await backup.handleListRemoteBackups()
    expect(backup.remoteWebdavFiles.value).toEqual([])
    expect(backup.remoteWebdavMessage.value).toBe('forbidden')
    expect(toastSpy.error).toHaveBeenCalledWith('forbidden')
  })

  it('handleDownloadRemoteBackup ignores empty name', async () => {
    const { backup } = setup()
    await backup.handleDownloadRemoteBackup('')
    expect(api.downloadWebdavBackup).not.toHaveBeenCalled()
  })

  it('handleDownloadRemoteBackup notifies filename', async () => {
    api.downloadWebdavBackup.mockResolvedValue({ filename: 'b.tar.gz' })
    const { backup } = setup()
    await backup.handleDownloadRemoteBackup('b.tar.gz')
    expect(api.downloadWebdavBackup).toHaveBeenCalledWith('tok', 'b.tar.gz')
    expect(toastSpy.success).toHaveBeenCalled()
    expect(backup.remoteDownloadName.value).toBe('')
  })

  it('handleBackupExport webdav mode success refreshes status', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.exportBackupArchive.mockResolvedValue({ mode: 'webdav', filename: 'f.tar.gz' })
    api.getBackupStatus.mockResolvedValue({ webdav_configured: true })
    const { backup } = setup()
    await backup.handleBackupExport()
    expect(api.exportBackupArchive).toHaveBeenCalled()
    expect(backup.backupStatus.value).toEqual({ webdav_configured: true })
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('handleBackupExport defaults to webdav and validates webdav url', async () => {
    const { backup } = setup({
      webdavUrl: '',
    })
    await backup.handleBackupExport()
    expect(api.exportBackupArchive).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalledWith('settings.webdavRequired')
  })

  it('handleDirectDownloadBackup triggers download mode export without saving webdav settings', async () => {
    api.exportBackupArchive.mockResolvedValue({ mode: 'download', filename: 'archive.tar.gz' })
    api.getBackupStatus.mockResolvedValue({ webdav_configured: true })
    const { backup } = setup()
    await backup.handleDirectDownloadBackup()
    expect(api.saveGlobalSettings).not.toHaveBeenCalled()
    expect(api.exportBackupArchive).toHaveBeenCalledWith('tok', 'download')
    expect(toastSpy.success).toHaveBeenCalledWith('settings.backupExportSuccess')
  })

  it('handleWebdavTest reports success/failure from API', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.testWebdavBackup.mockResolvedValue({ success: true, message: 'pong' })
    const { backup } = setup()
    await backup.handleWebdavTest()
    expect(toastSpy.success).toHaveBeenCalledWith('pong')

    api.testWebdavBackup.mockResolvedValue({ success: false, message: 'nope' })
    await backup.handleWebdavTest()
    expect(toastSpy.error).toHaveBeenCalledWith('nope')
  })

  it('handleImportFile 读取失败时报错且不发起导入', async () => {
    const { backup } = setup()
    const file = new File(['{}'], 'cfg.json', { type: 'application/json' })
    const orig = FileReader.prototype.readAsText
    FileReader.prototype.readAsText = function (this: FileReader) {
      Object.defineProperty(this, 'error', {
        value: new DOMException('读取失败', 'NotReadableError'),
      })
      this.onerror?.({} as ProgressEvent<FileReader>)
    }
    backup.handleImportFile(file)
    await vi.waitFor(() => {
      expect(toastSpy.error).toHaveBeenCalled()
    })
    FileReader.prototype.readAsText = orig
    expect(api.importConfigPreview).not.toHaveBeenCalled()
    expect(api.importAllConfigs).not.toHaveBeenCalled()
  })

  it('handleImportFile aborts on preview errors', async () => {
    api.importConfigPreview.mockResolvedValue({
      errors: ['bad json'],
      conflicts: [],
      signs_count: 0,
      monitors_count: 0,
      settings_keys: [],
    })
    const { backup } = setup()
    const file = new File(['{}'], 'cfg.json', { type: 'application/json' })
    await new Promise<void>((resolve) => {
      const orig = FileReader.prototype.readAsText
      FileReader.prototype.readAsText = function (this: FileReader) {
        Object.defineProperty(this, 'result', { value: '{}' })
        this.onload?.({ target: this } as ProgressEvent<FileReader>)
      }
      void backup.handleImportFile(file).then(() => {
        queueMicrotask(async () => {
          await Promise.resolve()
          await Promise.resolve()
          FileReader.prototype.readAsText = orig
          resolve()
        })
      })
    })
    await vi.waitFor(() => {
      expect(api.importConfigPreview).toHaveBeenCalled()
    })
    expect(api.importAllConfigs).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('handleImportFile confirms then imports', async () => {
    api.importConfigPreview.mockResolvedValue({
      errors: [],
      conflicts: ['a'],
      signs_count: 2,
      monitors_count: 1,
      settings_keys: ['timezone'],
    })
    api.importAllConfigs.mockResolvedValue({
      message: 'done',
      warnings: [],
      errors: [],
    })
    confirmMock.confirm.mockResolvedValue(true)
    const { backup } = setup()
    const file = new File(['{}'], 'cfg.json', { type: 'application/json' })
    const orig = FileReader.prototype.readAsText
    FileReader.prototype.readAsText = function (this: FileReader) {
      Object.defineProperty(this, 'result', { value: '{"v":1}' })
      void this.onload?.({ target: this } as ProgressEvent<FileReader>)
    }
    backup.handleImportFile(file)
    await vi.waitFor(() => {
      expect(api.importAllConfigs).toHaveBeenCalledWith('tok', '{"v":1}', true)
    })
    expect(confirmMock.confirm).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
    FileReader.prototype.readAsText = orig
  })

  it('handleImportFile respects confirm cancel', async () => {
    api.importConfigPreview.mockResolvedValue({
      errors: [],
      conflicts: [],
      signs_count: 0,
      monitors_count: 0,
      settings_keys: [],
    })
    confirmMock.confirm.mockResolvedValue(false)
    const { backup } = setup()
    const orig = FileReader.prototype.readAsText
    FileReader.prototype.readAsText = function (this: FileReader) {
      Object.defineProperty(this, 'result', { value: '{}' })
      void this.onload?.({ target: this } as ProgressEvent<FileReader>)
    }
    backup.handleImportFile(new File(['{}'], 'c.json'))
    await vi.waitFor(() => {
      expect(api.importConfigPreview).toHaveBeenCalled()
    })
    expect(api.importAllConfigs).not.toHaveBeenCalled()
    FileReader.prototype.readAsText = orig
  })

  it('loadBackupStatus sets backupStatus', async () => {
    api.getBackupStatus.mockResolvedValue({ ok: true })
    const { backup } = setup()
    await backup.loadBackupStatus('tok')
    expect(backup.backupStatus.value).toEqual({ ok: true })
  })

  it('validate path: password required when not set', async () => {
    const { backup } = setup({
      webdavUrl: 'https://x',
      webdavUsername: 'u',
      webdavPassword: '',
    })
    await backup.handleWebdavTest()
    expect(api.testWebdavBackup).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('handleBackupExport download 模式走本地下载提示', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.exportBackupArchive.mockResolvedValue({ mode: 'download', filename: 'b.tar.gz' })
    api.getBackupStatus.mockResolvedValue({ webdav_configured: false })
    const { backup } = setup()
    await backup.handleBackupExport()
    expect(toastSpy.success).toHaveBeenCalledWith('settings.backupExportSuccess')
    expect(backup.backupStatus.value).toEqual({ webdav_configured: false })
  })
})
