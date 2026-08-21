/**
 * TaskListCard 操作按钮语义测试：
 * 暂停任务时 run 按钮应禁用（与整卡视觉不可用一致）；
 * 忙碌态按钮禁用且点击不触发事件。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskListCard from '../components/tasks/TaskListCard.vue'
import { makeTaskUi } from './composable-test-utils'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

type ExtraProps = Record<string, unknown>

function mountCard(overrides: Record<string, unknown> = {}) {
  const task = makeTaskUi({
    name: 't1',
    id: 't1',
    raw: {
      name: 't1',
      account_name: 'acc1',
      account_names: ['acc1'],
      execution_mode: 'fixed',
      ...((overrides.raw as ExtraProps) || {}),
    },
    ...(overrides as ExtraProps),
  })
  return mount(TaskListCard, {
    props: {
      task,
      selected: false,
      taskActiveRun: null,
      taskActiveRuns: [],
      activeRunBadgeText: '',
      activeRunTooltip: '',
      hasInvalidAccount: false,
      toggleBusyKey: '',
      cancelBusyKey: '',
      runBusyKey: '',
      cloneBusy: false,
      deleteBusyKey: '',
      ...((overrides.props as ExtraProps) || {}),
    },
  })
}

describe('TaskListCard run button', () => {
  it('启用任务时 run 按钮可用并触发事件', async () => {
    const wrapper = mountCard()
    const runBtn = wrapper.findAll('button').find((b) => b.text().includes('execute'))
    expect(runBtn).toBeDefined()
    expect((runBtn!.element as HTMLButtonElement).disabled).toBe(false)
    await runBtn!.trigger('click')
    expect(wrapper.emitted('run')).toHaveLength(1)
  })

  it('暂停任务时 run 按钮禁用且不触发事件', async () => {
    const wrapper = mountCard({ enabled: false })
    const runBtn = wrapper.findAll('button').find((b) => b.text().includes('execute'))
    expect((runBtn!.element as HTMLButtonElement).disabled).toBe(true)
    await runBtn!.trigger('click')
    expect(wrapper.emitted('run')).toBeUndefined()
  })

  it('runTaskBusy 时按钮禁用（防重复点击）', async () => {
    const wrapper = mountCard({ props: { runBusyKey: 't1:acc1' } })
    const runBtn = wrapper.findAll('button').find((b) => b.text().includes('execute'))
    expect((runBtn!.element as HTMLButtonElement).disabled).toBe(true)
    await runBtn!.trigger('click')
    expect(wrapper.emitted('run')).toBeUndefined()
  })
})
