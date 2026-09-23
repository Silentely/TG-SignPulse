/**
 * FilterChip：可清除筛选 chip 的结构、色板与事件。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import FilterChip from '../components/FilterChip.vue'

describe('FilterChip', () => {
  it('默认 sky 色板，渲染插槽文案与关闭图标', () => {
    const wrapper = mount(FilterChip, {
      slots: { default: '账号: alice' },
    })
    expect(wrapper.text()).toContain('账号: alice')
    // 关闭图标：lucide 渲染为 svg
    expect(wrapper.find('button svg').exists()).toBe(true)
    expect(wrapper.classes()).toContain('ui-chip-sky')
  })

  it('tone 映射到对应 ui-chip-* 色板类', () => {
    for (const tone of ['violet', 'emerald', 'orange', 'amber', 'rose', 'teal', 'gray'] as const) {
      const wrapper = mount(FilterChip, { props: { tone } })
      expect(wrapper.classes()).toContain(`ui-chip-${tone}`)
    }
  })

  it('truncate 时加宽度上限与截断类，否则不加', () => {
    const truncated = mount(FilterChip, { props: { truncate: true } })
    expect(truncated.classes()).toContain('max-w-[12rem]')
    expect(truncated.find('span').classes()).toContain('truncate')

    const plain = mount(FilterChip)
    expect(plain.classes()).not.toContain('max-w-[12rem]')
    expect(plain.find('span').classes()).not.toContain('truncate')
  })

  it('title 透传到按钮', () => {
    const wrapper = mount(FilterChip, { props: { title: '清除筛选' } })
    expect(wrapper.attributes('title')).toBe('清除筛选')
  })

  it('点击触发 clear 事件', async () => {
    const wrapper = mount(FilterChip)
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('渲染为 button 且 type=button，避免提交所在表单', () => {
    const wrapper = mount(FilterChip)
    expect(wrapper.find('button').attributes('type')).toBe('button')
  })
})
