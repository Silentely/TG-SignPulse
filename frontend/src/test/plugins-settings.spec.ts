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

  it('当存在加载错误时展示诊断告警条并支持展开查看详情', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        builtin: true,
        enabled: true,
      },
    ])
    vi.spyOn(pluginsApi, 'getPluginDiagnostics').mockResolvedValueOnce({
      total_loaded: 1,
      total_errors: 1,
      load_errors: [
        {
          file_path: 'plugins/broken.py',
          plugin_name: 'broken',
          error_type: 'missing_dependency',
          error_message: '缺少依赖模块 requests',
          missing_module: 'requests',
          suggested_command: 'pip install requests',
        },
      ],
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('缺少依赖或语法错误')
    })

    // 点击展开详情
    const toggleDiagBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看详情'))
    expect(toggleDiagBtn).toBeDefined()
    await toggleDiagBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('pip install requests')
      expect(wrapper.text()).toContain('缺少依赖')
    })
  })

  it('当插件包含运行指标 metrics 时展示调用次数与成功率', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        enabled: true,
        metrics: {
          run_count: 42,
          success_count: 40,
          failure_count: 2,
          last_run_at: '2026-09-11 12:00:00',
          last_duration_ms: 15.2,
          avg_duration_ms: 18.5,
          success_rate: 95.2,
          last_error: null,
        },
      },
    ])
    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
      expect(wrapper.text()).toContain('42')
      expect(wrapper.text()).toContain('95.2%')
      expect(wrapper.text()).toContain('18.5ms')
    })
  })

  it('卡片中存在导出源码按钮，且顶部工具栏包含上传插件按钮', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'math_solver',
        mode: 'reactive',
        description: '数学计算',
        enabled: true,
      },
    ])
    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('math_solver')
    })
    expect(wrapper.text()).toContain('导出源码')
    expect(wrapper.text()).toContain('上传插件')
  })



  it('展示插件权限标签和运行指标重置按钮并支持重置', async () => {
    const mockPlugins = [
      {
        name: 'perm_plugin',
        mode: 'reactive' as const,
        description: '有权限的插件',
        permissions: ['send_message', 'network'],
        enabled: true,
        metrics: {
          run_count: 10,
          success_count: 9,
          failure_count: 1,
          success_rate: 90.0,
          avg_duration_ms: 15.2,
          last_run_at: '2026-09-11T12:00:00Z',
        },
      },
    ]
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue(mockPlugins)
    const resetSpy = vi.spyOn(pluginsApi, 'resetPluginMetrics').mockResolvedValueOnce({
      success: true,
      name: 'perm_plugin',
      message: 'ok',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('perm_plugin')
      expect(wrapper.text()).toContain('权限: send_message, network')
    })

    const resetBtn = wrapper.find('button[title="重置指标"]')
    expect(resetBtn.exists()).toBe(true)
    await resetBtn.trigger('click')
    expect(resetSpy).toHaveBeenCalledWith('perm_plugin', 'mock-token')
  })

  it('自定义插件源码弹窗支持切换编辑模式并保存更新', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([
      {
        name: 'custom_edit_plug',
        mode: 'reactive' as const,
        description: '可编辑插件',
        builtin: false,
        enabled: true,
      },
    ])
    vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValueOnce({
      name: 'custom_edit_plug',
      version: '1.0.0',
      source: 'print("original")',
    })
    const updateSpy = vi.spyOn(pluginsApi, 'updatePluginSource').mockResolvedValueOnce({
      name: 'custom_edit_plug',
      mode: 'reactive' as const,
      description: '可编辑插件',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('custom_edit_plug')
    })

    const sourceBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看源码'))
    await sourceBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('print("original")')
    })

    // 点击“编辑源码”
    const editBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('编辑源码'))
    expect(editBtn).toBeDefined()
    editBtn!.click()

    await vi.waitFor(() => {
      expect(document.querySelector('textarea')).not.toBeNull()
    })

    // 输入新内容并点击“保存并热重载”
    const textarea = document.querySelector('textarea')!
    textarea.value = 'print("modified")'
    textarea.dispatchEvent(new Event('input'))

    const saveBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('保存并热重载'))
    expect(saveBtn).toBeDefined()
    saveBtn!.click()

    expect(updateSpy).toHaveBeenCalledWith('custom_edit_plug', 'print("modified")', 'mock-token')
  })
})
