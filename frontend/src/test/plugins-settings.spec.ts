import { mount } from '@vue/test-utils'
import { useConfirm } from '../composables/useConfirm'
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
          last_duration_ms: 12.0,
          last_run_at: '2026-09-11T12:00:00Z',
          last_error: 'TimeoutError: plugin timed out',
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

  it('支持批量启用自定义插件与清空全部运行指标，并展示最近执行异常', async () => {
    const mockPlugins = [
      {
        name: 'custom_err_plug',
        mode: 'reactive' as const,
        description: '异常插件',
        builtin: false,
        enabled: false,
        metrics: {
          run_count: 5,
          success_count: 4,
          failure_count: 1,
          success_rate: 80.0,
          avg_duration_ms: 22.0,
          last_duration_ms: 15.0,
          last_run_at: '2026-09-11T12:00:00Z',
          last_error: 'ConnectionRefusedError: 无法连接目标主机',
        },
      },
    ]
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue(mockPlugins)
    const batchSpy = vi.spyOn(pluginsApi, 'batchTogglePlugins').mockResolvedValueOnce({
      success: true,
      count: 1,
      enabled: true,
    })
    const resetAllSpy = vi.spyOn(pluginsApi, 'resetAllPluginMetrics').mockResolvedValueOnce({
      success: true,
      message: 'ok',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('custom_err_plug')
      expect(wrapper.text()).toContain('最近执行异常: ConnectionRefusedError: 无法连接目标主机')
    })

    const batchEnableBtn = wrapper.findAll('button').find((b) => b.text().includes('全部启用自定义'))
    expect(batchEnableBtn).toBeDefined()
    await batchEnableBtn!.trigger('click')
    expect(batchSpy).toHaveBeenCalledWith(true, 'mock-token')

    const resetAllBtn = wrapper.find('button[title="清空全部指标"]')
    expect(resetAllBtn.exists()).toBe(true)
    const { accept } = useConfirm()
    void resetAllBtn.trigger('click')
    accept()
    await vi.waitFor(() => {
      expect(resetAllSpy).toHaveBeenCalledWith('mock-token')
    })
  })

  it('支持查看插件调用历史与克隆插件', async () => {
    const mockPlugins = [
      {
        name: 'plug_alpha',
        mode: 'reactive' as const,
        description: 'Alpha插件',
        builtin: false,
        enabled: true,
        metrics: {
          run_count: 10,
          success_count: 9,
          failure_count: 1,
          success_rate: 90.0,
          avg_duration_ms: 15.0,
          last_duration_ms: 12.0,
          last_run_at: '2026-09-11T12:00:00Z',
          last_error: null,
        },
      },
    ]
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue(mockPlugins)
    const historySpy = vi.spyOn(pluginsApi, 'getPluginHistory').mockResolvedValueOnce({
      name: 'plug_alpha',
      history: [
        {
          timestamp: '2026-09-11 12:00:00',
          duration_ms: 12.0,
          success: true,
          trigger_type: 'manual_test',
          log_summary: '执行成功',
        },
      ],
    })
    const cloneSpy = vi.spyOn(pluginsApi, 'clonePlugin').mockResolvedValueOnce({
      name: 'plug_alpha_copy',
      mode: 'reactive',
      description: 'Alpha插件',
      builtin: false,
      enabled: true,
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('plug_alpha')
    })

    // 1. 打开历史
    const historyBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '调用历史')
    expect(historyBtn).toBeDefined()
    await historyBtn!.trigger('click')
    expect(historySpy).toHaveBeenCalledWith('plug_alpha', 'mock-token')

    // 2. 打开克隆
    const cloneBtn = wrapper.findAll('button').find((b) => b.attributes('title') === '克隆')
    expect(cloneBtn).toBeDefined()
    await cloneBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('克隆插件')
    })

    const allButtons = Array.from(document.body.querySelectorAll('button'))
    const cloneSubmitBtn = allButtons.find((b) => b.textContent?.includes('确认'))
    expect(cloneSubmitBtn).toBeDefined()
    cloneSubmitBtn!.click()
    expect(cloneSpy).toHaveBeenCalledWith(
      'plug_alpha',
      {
        new_name: 'plug_alpha_copy',
        description: 'Alpha插件',
      },
      'mock-token',
    )
  })

  it('源码弹窗展示三方依赖检测且调试台支持快捷填入预设与参数重置默认', async () => {
    const mockPlugin = {
      name: 'smart_assistant',
      mode: 'reactive' as const,
      description: '智能助手',
      builtin: true,
      enabled: true,
      params_schema: [
        { name: 'threshold', label: '阈值', type: 'number' as const, default: 10 },
      ],
    }
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin as unknown as pluginsApi.PluginInfo])
    vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValue({
      name: 'smart_assistant',
      source: 'import requests\ndef smart_assistant_handler(): pass',
    })
    vi.spyOn(pluginsApi, 'getPluginDependencies').mockResolvedValue({
      name: 'smart_assistant',
      dependencies: [
        { module: 'requests', installed: true, version: '2.31.0' },
        { module: 'bs4', installed: false, install_command: 'pip install bs4' },
      ],
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('smart_assistant')
    })

    // 1. 打开查看源码弹窗，验证依赖展示
    const sourceBtn = wrapper.findAll('button').find((b) => b.text().includes('查看源码'))
    expect(sourceBtn).toBeDefined()
    await sourceBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('requests@2.31.0')
      expect(document.body.textContent).toContain('bs4')
      expect(document.body.textContent).toContain('未安装')
    })

    // 2. 打开调试弹窗，验证快捷填入与重置默认参数
    const testBtn = wrapper.findAll('button').find((b) => b.text().includes('调试'))
    expect(testBtn).toBeDefined()
    await testBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('快捷填入')
    })

    const allButtons = Array.from(document.body.querySelectorAll('button'))
    const mathPreset = allButtons.find((b) => b.textContent?.includes('数学算式'))
    expect(mathPreset).toBeDefined()
    mathPreset!.dispatchEvent(new MouseEvent('click', { bubbles: true }))

    await vi.waitFor(() => {
      const textarea = document.body.querySelector('textarea') as HTMLTextAreaElement
      expect(textarea.value).toBe('12 + 34 = ?')
    })

    const resetParamsBtn = allButtons.find((b) => b.textContent?.includes('恢复默认参数'))
    expect(resetParamsBtn).toBeDefined()
    resetParamsBtn!.click()
  })

  it('支持一键导出全部插件ZIP归档以及按异常筛选插件', async () => {
    const normalPlugin = {
      name: 'healthy_plugin',
      mode: 'reactive' as const,
      description: '健康插件',
      builtin: false,
      enabled: true,
      metrics: {
        run_count: 5,
        success_count: 5,
        failure_count: 0,
        last_run_at: '2026-09-11T20:00:00Z',
        last_duration_ms: 10,
        avg_duration_ms: 10,
        success_rate: 1.0,
        last_error: null,
      },
    }
    const issuePlugin = {
      name: 'broken_plugin',
      mode: 'reactive' as const,
      description: '异常插件',
      builtin: false,
      enabled: true,
      metrics: {
        run_count: 3,
        success_count: 1,
        failure_count: 2,
        last_run_at: '2026-09-11T20:00:00Z',
        last_duration_ms: 10,
        avg_duration_ms: 10,
        success_rate: 0.33,
        last_error: 'TimeoutError',
      },
    }

    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([normalPlugin, issuePlugin])
    const exportSpy = vi.spyOn(pluginsApi, 'exportAllPlugins').mockResolvedValue(
      new Blob(['fake zip'], { type: 'application/zip' }),
    )

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('healthy_plugin')
      expect(wrapper.text()).toContain('broken_plugin')
    })

    // 1. 点击导出全部 (ZIP)
    const exportAllBtn = wrapper.findAll('button').find((b) => b.text().includes('导出全部'))
    expect(exportAllBtn).toBeDefined()
    await exportAllBtn!.trigger('click')
    expect(exportSpy).toHaveBeenCalled()

    // 2. 点击筛选「异常/告警」
    const issueFilterBtn = wrapper.findAll('button').find((b) => b.text().includes('异常/告警'))
    expect(issueFilterBtn).toBeDefined()
    await issueFilterBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('broken_plugin')
      expect(wrapper.text()).not.toContain('healthy_plugin')
    })
  })

  it('自定义插件编辑模式下支持点击语法检查并展示通过状态', async () => {
    const mockPlugin = {
      name: 'syntax_test_p',
      mode: 'reactive' as const,
      description: '语法测试插件',
      builtin: false,
      enabled: true,
    }

    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin])
    vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValue({
      name: 'syntax_test_p',
      source: 'print("hello")',
    })
    const checkSyntaxSpy = vi.spyOn(pluginsApi, 'checkPluginSyntax').mockResolvedValue({
      valid: true,
      error: null,
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('syntax_test_p')
    })

    // 打开源码弹窗
    const sourceBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看源码'))
    expect(sourceBtn).toBeDefined()
    await sourceBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('print("hello")')
    })

    // 进入编辑模式
    const editBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('编辑源码'))
    expect(editBtn).toBeDefined()
    editBtn!.click()

    await vi.waitFor(() => {
      const syntaxBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('语法检查'))
      expect(syntaxBtn).toBeDefined()
    })

    // 点击语法检查
    const syntaxBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('语法检查'))
    syntaxBtn!.click()

    expect(checkSyntaxSpy).toHaveBeenCalledWith('print("hello")', 'mock-token')
  })

  it('调用历史弹窗中支持点击清空调用历史', async () => {
    const mockPlugin = {
      name: 'history_clear_p',
      mode: 'reactive' as const,
      description: '历史测试插件',
      builtin: true,
      enabled: true,
      metrics: {
        run_count: 3,
        success_count: 3,
        failure_count: 0,
        success_rate: 100,
        avg_duration_ms: 10,
        last_duration_ms: 10,
        last_run_at: null,
        last_error: null,
      },
    }

    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin])
    vi.spyOn(pluginsApi, 'getPluginHistory').mockResolvedValue({
      name: 'history_clear_p',
      history: [
        {
          timestamp: '2026-03-31 10:00:00',
          duration_ms: 12.0,
          success: true,
          trigger_type: 'manual_test',
          error: null,
          log_summary: 'ok',
        },
      ],
    })
    const clearSpy = vi.spyOn(pluginsApi, 'clearPluginHistory').mockResolvedValue({
      status: 'ok',
      name: 'history_clear_p',
      cleared_count: 1,
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('history_clear_p')
    })

    // 打开历史弹窗
    const histBtn = wrapper.findAll('button').find((b) => b.attributes('title')?.includes('调用历史'))
    expect(histBtn).toBeDefined()
    await histBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('2026-03-31 10:00:00')
    })

    // 点击清空历史按钮
    const clearBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('清空历史'))
    expect(clearBtn).toBeDefined()
    clearBtn!.click()
    const { accept } = await import('../composables/useConfirm').then(m => m.useConfirm())
    accept()

    await vi.waitFor(() => {
      expect(clearSpy).toHaveBeenCalledWith('history_clear_p', 'mock-token')
    })
  })

  it('当插件存在 doc 时展示文档按钮并能打开说明文档弹窗', async () => {
    const mockPlugin = {
      name: 'doc_demo_plugin',
      mode: 'reactive' as const,
      description: '带文档的演示插件',
      doc: '## 配置指南\n这是详细的插件文档说明。',
      builtin: true,
      enabled: true,
    }

    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin])

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('doc_demo_plugin')
    })

    // 找到文档按钮
    const docBtn = wrapper.findAll('button').find((b) => b.attributes('title')?.includes('文档') || b.text().includes('文档'))
    expect(docBtn).toBeDefined()
    await docBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('配置指南')
      expect(document.body.textContent).toContain('这是详细的插件文档说明。')
    })
  })

  it('点击批量重置指标时展示确认对话框并在确认后调用 resetAllPluginMetrics', async () => {
    const mockPlugin: any = {
      name: 'metrics_p',
      mode: 'reactive' as const,
      description: '演示插件',
      enabled: true,
      metrics: { run_count: 5, success_count: 5, failure_count: 0, success_rate: 100 },
    }
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin])
    const resetSpy = vi.spyOn(pluginsApi, 'resetAllPluginMetrics').mockResolvedValue({ success: true, message: 'ok' })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('metrics_p')
    })

    const resetAllBtn = wrapper.find('button[title*="清空全部指标"]')
    expect(resetAllBtn).toBeDefined()

    const { accept } = useConfirm()
    void resetAllBtn.trigger('click')
    accept()

    await vi.waitFor(() => {
      expect(resetSpy).toHaveBeenCalled()
    })
  })

  it('自定义插件编辑源码时支持切换Diff差异对比视图', async () => {
    const mockPlugin: any = {
      name: 'custom_diff_plug',
      mode: 'reactive' as const,
      description: 'Diff测试插件',
      enabled: true,
      builtin: false,
    }
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([mockPlugin])
    vi.spyOn(pluginsApi, 'getPluginSource').mockResolvedValue({
      name: 'custom_diff_plug',
      source: 'def run():\n    return 1',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('custom_diff_plug')
    })

    const sourceBtn = wrapper.findAll('button').find((btn) => btn.text().includes('查看源码'))
    expect(sourceBtn).toBeDefined()
    await sourceBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('def run():')
    })

    const editBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('编辑源码'))
    expect(editBtn).toBeDefined()
    editBtn!.click()

    await vi.waitFor(() => {
      expect(document.querySelector('textarea')).not.toBeNull()
    })

    const diffBtn = Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.includes('改动对比') || b.textContent?.includes('Diff'))
    expect(diffBtn).toBeDefined()
    diffBtn!.click()

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('返回编辑')
    })
  })
})
