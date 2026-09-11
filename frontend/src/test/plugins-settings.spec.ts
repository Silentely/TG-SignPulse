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

  it('展示插件列表及启用/停用软开关状态与元数据徽章', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学验证码自动计算',
        version: '1.2.0',
        updated_at: '2026-09-11',
        author: 'TG-SignPulse Team',
        source_path: '/data/plugins/math_solver.py',
        enabled: true,
        builtin: true,
      },
      {
        name: 'disabled_helper',
        mode: 'active',
        description: '已停用的辅助插件',
        version: '1.0.0',
        updated_at: '2026-09-10',
        author: 'Custom Dev',
        source_path: '/data/plugins/disabled_helper.py',
        enabled: false,
        builtin: false,
      },
    ])

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
      expect(wrapper.text()).toContain('disabled_helper')
    })

    // 检查软开关、内置/自定义标签与版本徽章
    expect(wrapper.text()).toContain('已启用')
    expect(wrapper.text()).toContain('已停用')
    expect(wrapper.text()).toContain('v1.2.0')
    expect(wrapper.text()).toContain('TG-SignPulse Team')
    expect(wrapper.text()).toContain('2026-09-11')
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

    const toggleBtn = wrapper.findAll('button').find((btn) => btn.text().includes('已启用'))
    expect(toggleBtn).toBeDefined()
    await toggleBtn!.trigger('click')

    expect(toggleSpy).toHaveBeenCalledWith('math_solver', 'mock-token')
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('已停用')
    })
  })

  it('点击查看源码按钮调用 getPluginSource 并打开源码弹窗', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        version: '1.0.0',
        enabled: true,
      },
    ])
    const sourceSpy = vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValueOnce({
      name: 'math_solver',
      version: '1.0.0',
      source: 'def math_solver_handler(): pass',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
    })

    const sourceBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看源码'))
    expect(sourceBtn).toBeDefined()
    await sourceBtn!.trigger('click')

    expect(sourceSpy).toHaveBeenCalledWith('math_solver', 'mock-token')
    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('def math_solver_handler(): pass')
    })
  })

  it('对于自定义插件展示删除按钮并支持删除', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'custom_plugin',
        mode: 'reactive',
        description: '自定义插件',
        builtin: false,
        enabled: true,
      },
    ])
    vi.spyOn(pluginsApi, 'deletePlugin').mockResolvedValueOnce({
      success: true,
      name: 'custom_plugin',
      message: '已删除',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('custom_plugin')
    })

    const deleteBtn = wrapper.findAll('button').find((btn) => btn.text().includes('删除'))
    expect(deleteBtn).toBeDefined()
  })

  it('支持通过搜索框过滤插件列表', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        builtin: true,
        enabled: true,
      },
      {
        name: 'webhook_pusher',
        mode: 'active',
        description: 'Webhook推送',
        builtin: true,
        enabled: true,
      },
    ])

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
      expect(wrapper.text()).toContain('webhook_pusher')
    })

    const searchInput = wrapper.find('input[type="text"]')
    expect(searchInput.exists()).toBe(true)
    await searchInput.setValue('webhook')

    expect(wrapper.text()).toContain('webhook_pusher')
    expect(wrapper.text()).not.toContain('math_solver')
  })

  it('在源码弹窗中提供前往调试按钮并能切换至调试弹窗', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        builtin: true,
        enabled: true,
      },
    ])
    vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValueOnce({
      name: 'math_solver',
      version: '1.0.0',
      source: 'def math_solver_handler(): pass',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
    })

    const sourceBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看源码'))
    await sourceBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('def math_solver_handler(): pass')
      expect(document.body.textContent).toContain('前往调试')
    })
  })
})
