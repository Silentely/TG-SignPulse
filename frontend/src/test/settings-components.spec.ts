import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import AboutSettings from '../components/settings/AboutSettings.vue'
import GeneralSettings from '../components/settings/GeneralSettings.vue'
import DataManagementSettings from '../components/settings/DataManagementSettings.vue'
import type { SettingsFormState } from '../lib/settings-form'

const settingsState = (): SettingsFormState => ({
  checkInterval: '',
  logDays: 7,
  dataDir: '',
  proxy: '',
  concurrency: 1,
  deviceKeepaliveEnabled: true,
  deviceKeepaliveIntervalDays: 30,
  botEnabled: false,
  botLoginNotify: false,
  botTaskFailure: true,
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
  webdavUrl: '',
  webdavUsername: '',
  webdavPassword: '',
  webdavRemoteDir: 'tg-signpulse-backups',
  backupTarget: 'auto',
})

describe('设置页拆分组件契约', () => {
  it('AboutSettings 展示后端 current_rss_mb 字段', () => {
    const wrapper = mount(AboutSettings, {
      props: {
        appVersion: null,
        runtimeStatus: {
          ready: true,
          scheduler_lock_held: true,
          legacy_tasks_writable: false,
          legacy_tasks_removed: true,
          database_is_sqlite: true,
          monitor_shard: '',
          monitor_allowlist: '',
        },
        memoryStats: { available: true, stats: { current_rss_mb: 128.456 } },
        versionBanner: null,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('128.5 MB')
  })

  it('GeneralSettings 清空数字输入时保留空值而不是转换为 0', async () => {
    const wrapper = mount(GeneralSettings, {
      props: {
        modelValue: settingsState(),
        timezoneOptions: [],
      },
      global: { plugins: [i18n] },
    })

    await wrapper.find('input[type="number"]').setValue('')

    const updates = wrapper.emitted('update:modelValue')
    expect(updates).toBeTruthy()
    expect((updates?.at(-1)?.[0] as SettingsFormState).logDays).toBe('')
  })

  it('DataManagementSettings WebDAV 区块可编辑并转发事件', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    await wrapper.find('#webdav-url').setValue('https://dav.example.com')
    await wrapper.find('#webdav-username').setValue('bk')
    const update = wrapper.emitted('update:modelValue')
    expect((update?.at(-1)?.[0] as SettingsFormState).webdavUsername).toBe('bk')
    expect((update?.at(-2)?.[0] as SettingsFormState).webdavUrl).toBe(
      'https://dav.example.com',
    )

    const findBtn = (label: string) => {
      return wrapper.findAll('button').find((b) => b.text().trim() === label)
    }
    const wdTest = findBtn('测试连接')
    const wdList = findBtn('列出远端备份')
    expect(wdTest).toBeTruthy()
    expect(wdList).toBeTruthy()
    await wdTest?.trigger('click')
    await wdList?.trigger('click')
    expect(wrapper.emitted('webdav-test')).toBeTruthy()
    expect(wrapper.emitted('webdav-list')).toBeTruthy()
  })

  it('DataManagementSettings WebDAV 远端列表逐条触发下载', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [{ name: 'auto-1.tar.gz', size_bytes: 10, mtime: 't' }],
        remoteMessage: 'settings.webdavListOk',
        remoteDownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('auto-1.tar.gz')
    await wrapper.find('li button').trigger('click')
    expect(wrapper.emitted('webdav-download')?.[0]).toEqual(['auto-1.tar.gz'])
  })

  it('DataManagementSettings 支持配置 backupTarget 与查看恢复指引', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: {
          data_dir: '/opt/tg-data',
          writable: true,
          size_bytes: 1024,
          size_human: '1 KB',
          recommended_paths: [],
        },
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    // 测试 backupTarget 变更
    const select = wrapper.find('#backup-target')
    expect(select.exists()).toBe(true)
    await select.setValue('webdav')
    const emitted = wrapper.emitted('update:modelValue')
    expect((emitted?.at(-1)?.[0] as SettingsFormState).backupTarget).toBe('webdav')

    // 测试恢复指引弹窗
    const guideBtn = wrapper.findAll('button').find((b) => b.text().includes('恢复指引'))
    expect(guideBtn).toBeTruthy()
    await guideBtn?.trigger('click')
    expect(document.body.textContent).toContain('docker stop tg-signpulse')
    expect(document.body.textContent).toContain('tar -xzf tg-signpulse-backup-*.tar.gz -C "<宿主机数据挂载目录，如 ./data>"')

    // 切换到宿主机 Tab
    const hostTab = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('宿主机'))
    expect(hostTab).toBeTruthy()
    hostTab?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('pkill -f "backend.main"')
    expect(document.body.textContent).toContain('tar -xzf tg-signpulse-backup-*.tar.gz -C "/opt/tg-data"')
  })

  it('DataManagementSettings 支持点击 WebDAV 快捷预设填充模版', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    const jgyBtn = wrapper.findAll('button').find((b) => b.text().includes('坚果云'))
    expect(jgyBtn).toBeTruthy()
    await jgyBtn?.trigger('click')
    const emitted = wrapper.emitted('update:modelValue')
    const last = emitted?.at(-1)?.[0] as SettingsFormState
    expect(last.webdavUrl).toContain('jianguoyun.com/dav')
  })

  it('DataManagementSettings 支持完整数据归档直接下载', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    const downloadBtn = wrapper.findAll('button').find((b) => b.text().includes('下载当前完整备份包'))
    expect(downloadBtn).toBeTruthy()
    await downloadBtn?.trigger('click')
    expect(wrapper.emitted('backup-download')).toBeTruthy()
  })
})
