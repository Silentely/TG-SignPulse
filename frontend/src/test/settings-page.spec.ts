import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import Settings from '../views/Settings.vue'
import TaskRuntimeSettings from '../components/settings/TaskRuntimeSettings.vue'

// 父页只负责编排：这里 mock 掉数据层与重型子卡，保留 TaskRuntimeSettings 真实渲染，
// 用于守护「任务执行策略卡确实被 Settings.vue 挂载并绑定保存事件」这一接线。
const spies = vi.hoisted(() => ({ saveAiRuntime: vi.fn() }))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

vi.mock('../composables/useSettingsPage', () => ({
  useSettingsPage: () => ({
    t: (key: string) => key,
    settings: ref({
      execTimeout: 60,
      accountCooldown: 5,
      flowRetry: 3,
      historyMaxAge: 7,
      aiVisionTimeout: 30,
      aiVisionRetry: 2,
      aiVisionReasoningEffort: '',
    }),
    timezoneOptions: [],
    tgConfig: ref({}),
    aiConfig: ref({}),
    aiKeyDecryptFailed: ref(false),
    loading: ref(false),
    tgLoading: ref(false),
    aiLoading: ref(false),
    aiRuntimeLoading: ref(false),
    dataLoading: ref(false),
    backupLoading: ref(false),
    backupStatus: ref(null),
    runtimeStatus: ref(null),
    memoryStats: ref(null),
    advancedLoading: ref(false),
    botTestLoading: ref(false),
    pageLoading: ref(false),
    loadFailed: ref(false),
    revealSecrets: ref({ tgApiId: false, tgApiHash: false, aiKey: false, botToken: false }),
    isDirty: ref(false),
    dirtyLabels: ref([]),
    appVersion: ref(''),
    versionLoading: ref(false),
    checkLoading: ref(false),
    versionBanner: ref(null),
    botLoading: ref(false),
    keepaliveLoading: ref(false),
    saveAllLoading: ref(false),
    webdavTestLoading: ref(false),
    webdavListLoading: ref(false),
    remoteWebdavFiles: ref([]),
    remoteWebdavMessage: ref(''),
    webdavPasswordSet: ref(false),
    botTokenSet: ref(false),
    proxySet: ref(false),
    remoteDownloadName: ref(''),
    saveSettings: vi.fn(),
    runKeepaliveNow: vi.fn(),
    saveBotSettings: vi.fn(),
    saveAdvancedSettings: vi.fn(),
    saveAllSettings: vi.fn(),
    testBot: vi.fn(),
    saveTgConfig: vi.fn(),
    resetTgConfig: vi.fn(),
    saveAiConfig: vi.fn(),
    saveAiRuntime: spies.saveAiRuntime,
    testAi: vi.fn(),
    handleExport: vi.fn(),
    handleImportFile: vi.fn(),
    handleBackupExport: vi.fn(),
    handleDirectDownloadBackup: vi.fn(),
    handleArchiveImport: vi.fn(),
    handleWebdavTest: vi.fn(),
    handleListRemoteBackups: vi.fn(),
    handleDownloadRemoteBackup: vi.fn(),
    handleCheckUpdate: vi.fn(),
    toggleReveal: vi.fn(),
    reload: vi.fn(),
  }),
}))

vi.mock('../components/settings/GeneralSettings.vue', () => ({
  default: { template: '<div data-testid="general-settings" />' },
}))
vi.mock('../components/settings/TelegramApiSettings.vue', () => ({
  default: { template: '<div data-testid="tg-settings" />' },
}))
vi.mock('../components/settings/DataManagementSettings.vue', () => ({
  default: { template: '<div data-testid="data-management" />' },
}))
vi.mock('../components/settings/AiSettings.vue', () => ({
  default: { template: '<div data-testid="ai-settings" />' },
}))
vi.mock('../components/settings/JevSettings.vue', () => ({
  default: { template: '<div data-testid="jev-settings" />' },
}))
vi.mock('../components/settings/BotNotifySettings.vue', () => ({
  default: { template: '<div data-testid="bot-settings" />' },
}))
vi.mock('../components/settings/DataDictSettings.vue', () => ({
  default: { template: '<div data-testid="data-dict-settings" />' },
}))
vi.mock('../components/settings/AboutSettings.vue', () => ({
  default: { template: '<div data-testid="about-settings" />' },
}))

describe('Settings 页面接线', () => {
  beforeEach(() => {
    spies.saveAiRuntime.mockClear()
  })

  it('渲染任务执行策略卡并暴露全部运行时字段', () => {
    const wrapper = mount(Settings)

    expect(wrapper.findComponent(TaskRuntimeSettings).exists()).toBe(true)
    expect(wrapper.text()).toContain('settings.taskRuntime')
    for (const id of [
      'ai-exectimeout',
      'ai-accountcooldown',
      'ai-flowretry',
      'ai-historymaxage',
      'ai-aivisiontimeout',
      'ai-aivisionretry',
      'ai-aivisionreasoning',
    ]) {
      expect(wrapper.find(`#${id}`).exists()).toBe(true)
    }
  })

  it('任务执行策略卡的保存事件转发到 saveAiRuntime', async () => {
    const wrapper = mount(Settings)
    await wrapper.findComponent(TaskRuntimeSettings).vm.$emit('save')
    expect(spies.saveAiRuntime).toHaveBeenCalledTimes(1)
  })
})
