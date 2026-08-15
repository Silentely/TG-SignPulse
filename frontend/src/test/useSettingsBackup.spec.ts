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
      {
        createObjectURL: vi.fn(() => 'blob:mock'),
        revokeObjectURL: vi.fn(),
      } as unknown as typeof URL,
    )
  })

  function setup(settingsOver: Partial<SettingsFormState> = {}) {
    const settings = ref(baseSettings(settingsOver))
    const markSectionClean = vi.fn()
    const backup = useSettingsBackup({
      settings,
      buildBackupPayload: () => ({ backup: true }),
      markSectionClean,
    })
    return { backup, settings, markSectionClean }
  }

  it('handleExport downloads config json', async () => {
    api.exportAllConfigs.mockResolvedValue('{"ok":1}')
    const click = vi.fn()
    const appendChild = vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n)
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag) as HTMLAnchorElement
      if (tag === 'a') {
        el.click = click
        el.remove = vi.fn()
      }
      return el
    })

    const { backup } = setup()
    await backup.handleExport()
    expect(api.exportAllConfigs).toHaveBeenCalledWith('tok')
    expect(click).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
    expect(backup.dataLoading.value).toBe(false)
    appendChild.mockRestore()
  })

  it('handleListRemoteBackups requires webdav url', async () => {
    const { backup } = setup({ webdavUrl: '' })
    await backup.handleListRemoteBackups()
    expect(api.listWebdavBackupFiles).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('handleListRemoteBackups saves settings then lists files', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.listWebdavBackupFiles.mockResolvedValue({
      success: true,
      files: [{ name: 'b1.zip', size: 1 }],
      message: 'ok',
    })
    const { backup, markSectionClean, settings } = setup({
      webdavPassword: 'secret',
    })
    await backup.handleListRemoteBackups()
    expect(api.saveGlobalSettings).toHaveBeenCalledWith('tok', { backup: true })
    expect(markSectionClean).toHaveBeenCalledWith('advanced')
    expect(backup.remoteWebdavFiles.value).toHaveLength(1)
    // afterWebdavSettingsSaved clears password
    expect(settings.value.webdavPassword).toBe('')
    expect(backup.webdavPasswordSet.value).toBe(true)
  })

  it('handleListRemoteBackups surfaces API failure message', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.listWebdavBackupFiles.mockResolvedValue({
      success: false,
      message: 'denied',
      files: [],
    })
    const { backup } = setup()
    await backup.handleListRemoteBackups()
    expect(toastSpy.error).toHaveBeenCalledWith('denied')
    expect(backup.remoteWebdavFiles.value).toEqual([])
  })

  it('handleDownloadRemoteBackup notifies filename', async () => {
    api.downloadWebdavBackup.mockResolvedValue({ filename: 'x.zip' })
    const { backup } = setup()
    await backup.handleDownloadRemoteBackup('x.zip')
    expect(api.downloadWebdavBackup).toHaveBeenCalledWith('tok', 'x.zip')
    expect(toastSpy.success).toHaveBeenCalled()
    expect(backup.remoteDownloadName.value).toBe('')
  })

  it('handleBackupExport validates webdav form', async () => {
    const { backup } = setup({ webdavUrl: '', webdavUsername: '', webdavPassword: '' })
    await backup.handleBackupExport()
    expect(api.exportBackupArchive).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('handleBackupExport webdav mode success refreshes status', async () => {
    api.saveGlobalSettings.mockResolvedValue({})
    api.exportBackupArchive.mockResolvedValue({ mode: 'webdav', filename: 'f.zip' })
    api.getBackupStatus.mockResolvedValue({ last_backup_at: 't' })
    const { backup } = setup()
    await backup.handleBackupExport()
    expect(api.exportBackupArchive).toHaveBeenCalled()
    expect(backup.backupStatus.value).toEqual({ last_backup_at: 't' })
    expect(toastSpy.success).toHaveBeenCalled()
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
        // handleImportFile itself returns before reader finishes; wait microtasks
        queueMicrotask(async () => {
          await Promise.resolve()
          await Promise.resolve()
          FileReader.prototype.readAsText = orig
          resolve()
        })
      })
    })
    // reader.onload is async
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
    // webdavPasswordSet default false
    await backup.handleWebdavTest()
    expect(api.testWebdavBackup).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()
  })
})
