import { mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import i18n from '../i18n'
import TaskFormActionsSection from '../components/tasks/TaskFormActionsSection.vue'
import * as pluginsApi from '../lib/api/plugins'

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
}))

describe('TaskFormActionsSection.vue 动作区插件调试集成', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
    })

    const debugBtn = wrapper.findAll('button').find((btn) => btn.text().includes('在线调试'))
    expect(debugBtn).toBeDefined()
    await debugBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('主动执行模式')
      expect(document.body.textContent).toContain('webhook_url')
    })
  })
})
