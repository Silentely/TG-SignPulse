import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import i18n from '../i18n'
import AboutSettings from '../components/settings/AboutSettings.vue'
import GeneralSettings from '../components/settings/GeneralSettings.vue'
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
  autoBackupEnabled: false,
  autoBackupInterval: 24,
  autoBackupKeep: 3,
  webdavUrl: '',
  webdavUsername: '',
  webdavPassword: '',
  webdavRemoteDir: 'tg-signpulse-backups',
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
})
