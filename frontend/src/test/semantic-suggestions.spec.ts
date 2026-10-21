import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '../i18n'
import TaskRuleSuggestionsPanel from '../components/tasks/TaskRuleSuggestionsPanel.vue'
import * as semanticApi from '../lib/api/semantic'

describe('TaskRuleSuggestionsPanel', () => {
  const dummySuggestions: semanticApi.RuleSuggestion[] = [
    {
      id: 'sug-1',
      scope: 'acc1:daily',
      account_name: 'acc1',
      task_name: 'daily',
      kind: 'button_label',
      status: 'pending',
      created_at: 1000,
      confidence: 0.98,
      patch: {
        op: 'replace',
        path: '/chats/0/actions/0/text',
        old: '签到',
        value: '点击签到',
      },
    },
  ]

  it('renders suggestions and handles apply flow', async () => {
    vi.spyOn(semanticApi, 'listRuleSuggestions').mockResolvedValue(dummySuggestions)
    const applySpy = vi.spyOn(semanticApi, 'applyRuleSuggestion').mockResolvedValue({
      status: 'applied',
      suggestion_id: 'sug-1',
      task: {},
    })

    const wrapper = mount(TaskRuleSuggestionsPanel, {
      props: {
        accountName: 'acc1',
        taskName: 'daily',
      },
      global: { plugins: [i18n] },
    })

    // 等待拉取完成
    await new Promise((r) => setTimeout(r, 20))
    expect(wrapper.text()).toContain('button_label')
    expect(wrapper.text()).toContain('/chats/0/actions/0/text')
    expect(wrapper.text()).toContain('98%')

    // 点击采纳
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('采纳并更新') || b.text().includes('Accept'))
    expect(applyBtn).toBeDefined()
    await applyBtn!.trigger('click')

    expect(applySpy).toHaveBeenCalledWith('sug-1', {
      account_name: 'acc1',
      task_name: 'daily',
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(wrapper.emitted('applied')).toBeTruthy()
  })

  it('handles 409 conflict and shows warning message', async () => {
    vi.spyOn(semanticApi, 'listRuleSuggestions').mockResolvedValue(dummySuggestions)
    vi.spyOn(semanticApi, 'applyRuleSuggestion').mockRejectedValue({
      status: 409,
      message: 'SEMANTIC_CONFIG_CHANGED: 任务配置已被修改',
    })

    const wrapper = mount(TaskRuleSuggestionsPanel, {
      props: {
        accountName: 'acc1',
        taskName: 'daily',
      },
      global: { plugins: [i18n] },
    })

    await new Promise((r) => setTimeout(r, 20))
    const applyBtn = wrapper.findAll('button').find((b) => b.text().includes('采纳并更新') || b.text().includes('Accept'))
    await applyBtn!.trigger('click')

    await new Promise((r) => setTimeout(r, 20))
    expect(wrapper.text()).toContain('任务配置在外部被修改，该规则建议已失效')
  })
})
