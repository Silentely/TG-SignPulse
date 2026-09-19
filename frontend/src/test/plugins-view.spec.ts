import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import router from '../router'
import i18n from '../i18n'
import { useAuthStore } from '../stores/auth'
import PluginsView from '../views/Plugins.vue'
import LayoutView from '../views/Layout.vue'
import TaskLogsHistoryPanel from '../components/tasks/TaskLogsHistoryPanel.vue'

vi.mock('../lib/api/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api/core')>()
  return {
    ...actual,
    withToken: vi.fn((cb) => cb('mock-token')),
    getAuthToken: vi.fn(() => 'mock-token'),
    request: vi.fn().mockResolvedValue({}),
  }
})

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    getAppVersion: vi.fn().mockResolvedValue({ version: '1.2.0' }),
    getPlugins: vi.fn().mockResolvedValue([]),
    getPluginDiagnostics: vi.fn().mockResolvedValue({}),
    getGlobalSettings: vi.fn().mockResolvedValue({}),
    getTelegramConfig: vi.fn().mockResolvedValue({}),
    getAIConfig: vi.fn().mockResolvedValue({}),
    getRuntimeStatus: vi.fn().mockResolvedValue({}),
    getMemoryStats: vi.fn().mockResolvedValue({}),
    getBackupStatus: vi.fn().mockResolvedValue(null),
    getSignTrends: vi.fn().mockResolvedValue({ trends: [] }),
  }
})

describe('PluginsView & 侧边栏菜单', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()

    const authStore = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    authStore.setToken(`header.${payload}.signature`)

    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    await router.push('/plugins')
  })

  it('路由配置中包含 plugins 子路由', () => {
    const layoutRoute = router.getRoutes().find(r => r.name === 'plugins')
    expect(layoutRoute).toBeDefined()
    expect(layoutRoute?.path).toBe('/plugins')
  })

  it('Layout 侧边栏导航中包含扩展插件菜单项', () => {
    const wrapper = mount(LayoutView, {
      global: {
        plugins: [i18n, router],
      },
    })

    const navLinks = wrapper.findAll('nav a')
    const navTexts = navLinks.map(l => l.text().trim())
    expect(navTexts).toContain('扩展插件')
  })

  it('Plugins.vue 正常挂载并渲染扩展插件容器', async () => {
    const wrapper = mount(PluginsView, {
      global: {
        plugins: [i18n, router],
      },
    })

    expect(wrapper.find('section').exists()).toBe(true)
    expect(wrapper.text()).toContain('扩展插件')
  })

  it('路由守卫 beforeEnter 检测到 /settings?tab=plugins 时重定向至 plugins', async () => {
    await router.push({ path: '/settings', query: { tab: 'plugins', testPlugin: 'my_plugin', testInput: 'hello' } })
    expect(router.currentRoute.value.name).toBe('plugins')
    expect(router.currentRoute.value.query).toEqual({ testPlugin: 'my_plugin', testInput: 'hello' })
  })

  it('路由守卫 beforeEnter 支持 tab 为数组或仅携带 testPlugin', async () => {
    await router.push({ path: '/settings', query: { tab: ['other', 'plugins'], foo: 'bar' } })
    expect(router.currentRoute.value.name).toBe('plugins')
    expect(router.currentRoute.value.query).toEqual({ foo: 'bar' })

    await router.push({ path: '/settings', query: { testPlugin: 'auto_action' } })
    expect(router.currentRoute.value.name).toBe('plugins')
    expect(router.currentRoute.value.query).toEqual({ testPlugin: 'auto_action' })
  })

  it('普通访问 /settings 保持正常不触发重定向', async () => {
    await router.push({ path: '/settings' })
    expect(router.currentRoute.value.name).toBe('settings')
  })

  it('TaskLogsHistoryPanel 中失败日志回放链接指向 plugins 路由', () => {
    const wrapper = mount(TaskLogsHistoryPanel, {
      props: {
        runAccount: 'test_acc',
        isRunning: false,
        livePhase: null,
        livePhaseDetail: '',
        liveState: null,
        liveStatusLabel: '',
        liveStatusToneClass: '',
        realtimeLogs: [],
        displayRealtimeLines: [],
        loading: false,
        logs: [
          {
            account_name: 'test_acc',
            time: '2026-09-19 09:00:00',
            success: false,
            message: '插件「sample_plugin」执行失败',
            bot_message: 'sample input message',
          },
        ],
        expandedIdx: null,
        formatDate: (d) => d,
        lineTone: () => '',
      },
      global: {
        plugins: [i18n, router],
      },
    })

    const replayLink = wrapper.findComponent({ name: 'RouterLink' })
    expect(replayLink.exists()).toBe(true)
    expect(replayLink.props('to')).toEqual({
      name: 'plugins',
      query: {
        testPlugin: 'sample_plugin',
        testInput: 'sample input message',
      },
    })
  })
})
