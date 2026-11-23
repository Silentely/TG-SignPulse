import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'
import i18n from '../i18n'
import TaskFormActionsSection from '../components/tasks/TaskFormActionsSection.vue'
import * as pluginsApi from '../lib/api/plugins'
import type { TaskActionItem } from '../lib/types'

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
}))

describe('TaskFormActionsSection.vue 动作区插件调试集成', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('在动作高级设置中配置 JEV 辅助模式和业务目标', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([])
    const action: TaskActionItem = {
      id: 1, type: 'click_text_button', value: '签到', aiPrompt: '', wait_for_reply: true,
    }
    const wrapper = mount(TaskFormActionsSection, {
      props: { actions: [action], stepNum: '2' },
      global: { plugins: [i18n] },
    })
    const advanced = wrapper.findAll('button').find(btn => btn.attributes('title')?.includes('高级'))
    expect(advanced).toBeDefined()
    await advanced!.trigger('click')
    const buttonLabel = wrapper.findAll('label').find(label => label.text().includes('JEV 按钮语义匹配'))!
    expect((buttonLabel.get('input').element as HTMLInputElement).checked).toBe(true)
    const editGoalButtons = wrapper.findAll('button').filter(btn => btn.text() === '自定义判断目标（可选）')
    expect(editGoalButtons.length).toBe(2)
    expect(wrapper.find('input[aria-label="按钮目标，例如：返回机器人主菜单"]').exists()).toBe(false)
    await editGoalButtons[0].trigger('click')
    await wrapper.get('input[aria-label="按钮目标，例如：返回机器人主菜单"]').setValue('完成每日签到')
    expect(action.semantic_button).toEqual({ mode: 'assist', goal: '完成每日签到' })
    const resultLabel = wrapper.findAll('label').find(label => label.text().includes('JEV 回复语义判定'))!
    expect((resultLabel.get('input').element as HTMLInputElement).checked).toBe(true)
    await resultLabel.get('input').setValue(false)
    await resultLabel.get('input').setValue(true)
    expect(action.semantic_result?.mode).toBe('assist')
    await buttonLabel.get('input').setValue(false)
    expect(action.semantic_button?.mode).toBe('off')
  })

  it('当动作类型为 custom_plugin 时展示在线调试按钮，并能打开内联调试弹窗', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([
      {
        name: 'webhook_pusher',
        mode: 'active' as const,
        description: '发送 Webhook 通知',
        version: '1.0.0',
        params_schema: [
          {
            name: 'webhook_url',
            label: '推送地址',
            type: 'string',
            default: 'https://example.com/api',
          },
        ],
      },
    ])

    const actions = [
      {
        id: 1,
        type: 'custom_plugin' as const,
        value: 'webhook_pusher',
        mode: 'active' as const,
        aiPrompt: '',
        continue_on_error: false,
        skip_if_matched: '',
        params: {
          webhook_url: 'https://test.local/hook',
        },
      },
    ]

    const wrapper = mount(TaskFormActionsSection, {
      props: {
        actions,
        stepNum: '2',
      },
      global: { plugins: [i18n] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('在线调试')
      expect(wrapper.text()).toContain('v1.0.0')
      expect(wrapper.text()).toContain('超时限制(秒)')
    })

    const debugBtn = wrapper.findAll('button').find((btn) => btn.text().includes('在线调试'))
    expect(debugBtn).toBeDefined()
    await debugBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('主动执行模式')
      expect(document.body.textContent).toContain('推送地址')
    })
  })

  it("默认以及显式允许时，自定义插件选项处于可用状态", async () => {
    vi.spyOn(pluginsApi, "getPlugins").mockResolvedValueOnce([])
    const actions = [
      {
        id: 1,
        type: "send_text" as const,
        value: "hello",
        aiPrompt: "",
        continue_on_error: false,
        skip_if_matched: "",
      },
    ]

    const wrapper = mount(TaskFormActionsSection, {
      props: {
        actions,
        stepNum: "04",
      },
      global: { plugins: [i18n] },
    })

    const customSelect = wrapper.findComponent({ name: "CustomSelect" })
    expect(customSelect.exists()).toBe(true)
    const options = customSelect.props("options") as Array<{ label: string; value: string; disabled?: boolean }>
    const pluginOpt = options.find((opt) => opt.value === "custom_plugin")
    expect(pluginOpt).toBeDefined()
    expect(pluginOpt?.disabled).toBe(false)
  })

  it('允许在回复确认的成功与失败匹配规则及重试关键词中正常回车换行并在失焦时清理', async () => {
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValueOnce([])
    const action: TaskActionItem = reactive({
      id: 1,
      type: 'send_text',
      value: '/checkin',
      aiPrompt: '',
      wait_for_reply: true,
      reply_success_patterns: ['签到成功'],
      reply_failure_patterns: ['签到失败'],
      reply_retry_keywords: ['重试'],
    })

    const wrapper = mount(TaskFormActionsSection, {
      props: { actions: [action], stepNum: '2' },
      global: { plugins: [i18n] },
    })

    const advanced = wrapper.findAll('button').find(btn => btn.attributes('title')?.includes('高级'))
    expect(advanced).toBeDefined()
    await advanced!.trigger('click')

    const textareas = wrapper.findAll('textarea')
    expect(textareas.length).toBeGreaterThanOrEqual(3)

    const successTextarea = textareas[0]
    expect((successTextarea.element as HTMLTextAreaElement).value).toBe('签到成功')

    // 模拟用户在成功规则后按回车键换行
    await successTextarea.setValue('签到成功\n')
    expect((successTextarea.element as HTMLTextAreaElement).value).toBe('签到成功\n')
    expect(action.reply_success_patterns).toEqual(['签到成功', ''])

    // 继续输入第二行
    await successTextarea.setValue('签到成功\n打卡成功')
    expect(action.reply_success_patterns).toEqual(['签到成功', '打卡成功'])

    // 尾部有多余换行，失焦时自动清理
    await successTextarea.setValue('签到成功\n打卡成功\n')
    await successTextarea.trigger('blur')
    await flushPromises()
    expect((successTextarea.element as HTMLTextAreaElement).value).toBe('签到成功\n打卡成功')
    expect(action.reply_success_patterns).toEqual(['签到成功', '打卡成功'])

    // 失败匹配规则回车换行测试
    const failureTextarea = textareas[1]
    expect((failureTextarea.element as HTMLTextAreaElement).value).toBe('签到失败')
    await failureTextarea.setValue('签到失败\n')
    expect((failureTextarea.element as HTMLTextAreaElement).value).toBe('签到失败\n')
    expect(action.reply_failure_patterns).toEqual(['签到失败', ''])
    await failureTextarea.setValue('签到失败\n操作超时')
    expect(action.reply_failure_patterns).toEqual(['签到失败', '操作超时'])
    await failureTextarea.trigger('blur')
    await flushPromises()
    expect(action.reply_failure_patterns).toEqual(['签到失败', '操作超时'])

    // 重试关键词回车换行测试
    const retryTextarea = textareas[2]
    expect((retryTextarea.element as HTMLTextAreaElement).value).toBe('重试')
    await retryTextarea.setValue('重试\n')
    expect((retryTextarea.element as HTMLTextAreaElement).value).toBe('重试\n')
    expect(action.reply_retry_keywords).toEqual(['重试', ''])
    await retryTextarea.setValue('重试\n稍后再试')
    expect(action.reply_retry_keywords).toEqual(['重试', '稍后再试'])
    await retryTextarea.trigger('blur')
    await flushPromises()
    expect(action.reply_retry_keywords).toEqual(['重试', '稍后再试'])
  })
})
