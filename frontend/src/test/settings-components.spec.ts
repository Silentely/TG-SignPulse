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
  s3Enabled: false,
  s3EndpointUrl: '',
  s3Bucket: '',
  s3AccessKey: '',
  s3SecretKey: '',
  s3Region: '',
  s3Prefix: '',
  s3Proxy: '',
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

  it('DataManagementSettings 对象存储区块可编辑并转发事件', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
        remoteS3Files: [],
        remoteS3Message: '',
        remoteS3DownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    await wrapper.find('#s3-endpoint-url').setValue('https://s3.example.com')
    await wrapper.find('#s3-bucket').setValue('bk')
    const update = wrapper.emitted('update:modelValue')
    // 无 v-model 回写时每次输入只携带自身字段的变更
    expect((update?.at(-1)?.[0] as SettingsFormState).s3Bucket).toBe('bk')
    expect((update?.at(-2)?.[0] as SettingsFormState).s3EndpointUrl).toBe(
      'https://s3.example.com',
    )

    await wrapper.find('[role="switch"]').trigger('click')
    const last = update?.at(-1)?.[0] as SettingsFormState
    expect(last.s3Enabled).toBe(true)

    // WebDAV 与对象存储共用「测试连接 / 列出远端备份」文案，取最后一组即为对象存储
    const pickLast = (label: string) => {
      const found = wrapper.findAll('button').filter((b) => b.text().trim() === label)
      return found.at(-1)
    }
    const s3Test = pickLast('测试连接')
    const s3List = pickLast('列出远端备份')
    expect(s3Test).toBeTruthy()
    expect(s3List).toBeTruthy()
    await s3Test?.trigger('click')
    await s3List?.trigger('click')
    expect(wrapper.emitted('s3-test')).toBeTruthy()
    expect(wrapper.emitted('s3-list')).toBeTruthy()
  })

  it('DataManagementSettings 对象存储远端列表逐条触发下载', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
        remoteS3Files: [{ name: 'auto-1.tar.gz', size_bytes: 10, mtime: 't' }],
        remoteS3Message: 'settings.s3ListOk',
        remoteS3DownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('auto-1.tar.gz')
    await wrapper.find('li button').trigger('click')
    expect(wrapper.emitted('s3-download')?.[0]).toEqual(['auto-1.tar.gz'])
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
          entries: [],
          recommended_paths: [],
        },
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
        remoteS3Files: [],
        remoteS3Message: '',
        remoteS3DownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    // 测试 backupTarget 变更
    const select = wrapper.find('#backup-target')
    expect(select.exists()).toBe(true)
    await select.setValue('both')
    const emitted = wrapper.emitted('update:modelValue')
    expect((emitted?.at(-1)?.[0] as SettingsFormState).backupTarget).toBe('both')

    // 测试恢复指引弹窗
    const guideBtn = wrapper.findAll('button').find((b) => b.text().includes('恢复指引'))
    expect(guideBtn).toBeTruthy()
    await guideBtn?.trigger('click')
    expect(document.body.textContent).toContain('docker stop tg-signpulse')
    expect(document.body.textContent).toContain('tar -xzf tg-signpulse-backup-*.tar.gz -C "<宿主机挂载目录，如 ./data>"')

    // 切换到宿主机 Tab
    const hostTab = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('宿主机'))
    expect(hostTab).toBeTruthy()
    hostTab?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(document.body.textContent).toContain('pkill -f "backend.main"')
    expect(document.body.textContent).toContain('tar -xzf tg-signpulse-backup-*.tar.gz -C "/opt/tg-data"')
  })

  it('DataManagementSettings 支持点击 S3 快捷预设填充模版', async () => {
    const wrapper = mount(DataManagementSettings, {
      props: {
        modelValue: settingsState(),
        backupStatus: null,
        remoteFiles: [],
        remoteMessage: '',
        remoteDownloadName: '',
        remoteS3Files: [],
        remoteS3Message: '',
        remoteS3DownloadName: '',
      },
      global: { plugins: [i18n] },
    })

    const r2Btn = wrapper.findAll('button').find((b) => b.text().includes('Cloudflare R2'))
    expect(r2Btn).toBeTruthy()
    await r2Btn?.trigger('click')
    const emitted = wrapper.emitted('update:modelValue')
    const last = emitted?.at(-1)?.[0] as SettingsFormState
    expect(last.s3EndpointUrl).toContain('r2.cloudflarestorage.com')
    expect(last.s3Region).toBe('auto')
    expect(last.s3Enabled).toBe(true)
  })
})
