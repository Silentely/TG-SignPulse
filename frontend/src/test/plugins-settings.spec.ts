import { mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import i18n from '../i18n'
import PluginsSettings from '../components/settings/PluginsSettings.vue'
import * as pluginsApi from '../lib/api/plugins'

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
  getAuthToken: vi.fn(() => 'mock-token'),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {},
  }),
}))

describe('PluginsSettings.vue 插件管理组件', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('展示插件列表及启用/停用软开关状态', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学验证码自动计算',
        source_path: '/data/plugins/math_solver.py',
        enabled: true,
      },
      {
        name: 'disabled_helper',
        mode: 'active',
        description: '已停用的辅助插件',
        source_path: '/data/plugins/disabled_helper.py',
        enabled: false,
      },
    ])

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    // 等待 loadPluginList 完成
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
      expect(wrapper.text()).toContain('disabled_helper')
    })

    // 检查启用和停用按钮文本
    expect(wrapper.text()).toContain('已启用')
    expect(wrapper.text()).toContain('已停用')
  })

  it('点击软开关按钮触发 togglePlugin 并更新界面状态', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        enabled: true,
      },
    ])
    const toggleSpy = vi.spyOn(pluginsApi, 'togglePlugin').mockResolvedValueOnce({
      name: 'math_solver',
      mode: 'reactive',
      description: '数学计算',
      enabled: false,
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
    })

    // 找到软开关按钮
    const toggleBtn = wrapper.findAll('button').find((btn) => btn.text().includes('已启用'))
    expect(toggleBtn).toBeDefined()
    await toggleBtn!.trigger('click')

    expect(toggleSpy).toHaveBeenCalledWith('math_solver', 'mock-token')
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('已停用')
    })
  })
})
