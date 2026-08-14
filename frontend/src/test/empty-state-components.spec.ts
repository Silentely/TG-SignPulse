/**
 * FilterEmptyState / PageRetry 组件：空态与错误态可交互结构。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { mockI18nPassthrough } from './composable-test-utils'
import FilterEmptyState from '../components/FilterEmptyState.vue'
import PageRetry from '../components/PageRetry.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))

describe('FilterEmptyState', () => {
  it('渲染标题与提示，无 actionText 时不渲染按钮', () => {
    const wrapper = mount(FilterEmptyState, {
      props: { title: '无结果', hint: '调整筛选条件' },
    })
    expect(wrapper.text()).toContain('无结果')
    expect(wrapper.text()).toContain('调整筛选条件')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('提供 actionText 时渲染按钮并触发 action 事件', async () => {
    const wrapper = mount(FilterEmptyState, {
      props: { title: '无结果', actionText: '清除筛选' },
    })
    const btn = wrapper.find('button')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('清除筛选')
    await btn.trigger('click')
    expect(wrapper.emitted('action')).toHaveLength(1)
  })
})

describe('PageRetry', () => {
  it('渲染默认加载失败文案与重试按钮', () => {
    const wrapper = mount(PageRetry, {
      props: { loading: false },
    })
    // mockI18nPassthrough 原样透传 key
    expect(wrapper.find('button').text()).toContain('common.retry')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('loading 时禁用按钮并触发 retry 事件', async () => {
    const wrapper = mount(PageRetry, {
      props: { loading: true },
    })
    const btn = wrapper.find('button')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    await btn.trigger('click')
    expect(wrapper.emitted('retry')).toBeUndefined()

    await wrapper.setProps({ loading: false })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
