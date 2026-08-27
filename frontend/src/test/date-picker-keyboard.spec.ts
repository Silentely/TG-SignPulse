/**
 * DatePicker 日历网格键盘可达性：
 * roving tabindex 仅一格可 Tab、方向键 ±1/±7 移动（跨月切视图）、
 * 打开即聚焦光标格、aria-current 标记今天、Esc 焦点归还触发按钮。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import DatePicker from '../components/DatePicker.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ locale: ref('zh'), t: (k: string) => k }),
}))

const pad2 = (n: number) => String(n).padStart(2, '0')
const todayStr = () => {
  const t = new Date()
  return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}-${pad2(t.getDate())}`
}

const openPicker = async (wrapper: any) => {
  await wrapper.find('button.ui-select-trigger').trigger('click')
  await wrapper.vm.$nextTick()
  await new Promise((r) => setTimeout(r, 0))
}

const dayCells = () =>
  Array.from(document.querySelectorAll<HTMLElement>('button[id*="-day-"]'))

describe('DatePicker 键盘导航', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('打开后焦点落在网格光标格，且仅一格 tabindex=0', async () => {
    const wrapper = mount(DatePicker, { props: { modelValue: '' }, attachTo: document.body })
    await openPicker(wrapper)
    const cells = dayCells()
    const tabbable = cells.filter((c) => c.tabIndex === 0)
    expect(tabbable.length).toBe(1)
    expect(document.activeElement).toBe(tabbable[0])
    // 默认光标：今天（在当前视图月内）
    expect(tabbable[0].id).toContain(todayStr())
    wrapper.unmount()
  })

  it('方向键移动光标：右 +1 天、下 +7 天', async () => {
    const wrapper = mount(DatePicker, { props: { modelValue: '' }, attachTo: document.body })
    await openPicker(wrapper)
    const start = document.activeElement as HTMLElement
    const startDate = new Date(start.id.replace(/^.*-day-/, '') + 'T00:00:00')

    start.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }))
    await new Promise((r) => setTimeout(r, 0))
    const after1 = document.activeElement as HTMLElement
    const d1 = new Date(after1.id.replace(/^.*-day-/, '') + 'T00:00:00')
    expect((d1.getTime() - startDate.getTime()) / 86400000).toBe(1)
    expect(after1.tabIndex).toBe(0)
    expect(start.tabIndex).toBe(-1)

    after1.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }))
    await new Promise((r) => setTimeout(r, 0))
    const after7 = document.activeElement as HTMLElement
    const d7 = new Date(after7.id.replace(/^.*-day-/, '') + 'T00:00:00')
    expect((d7.getTime() - d1.getTime()) / 86400000).toBe(7)
    wrapper.unmount()
  })

  it('今天格子带 aria-current="date"，选中格带 aria-selected', async () => {
    const wrapper = mount(DatePicker, { props: { modelValue: todayStr() }, attachTo: document.body })
    await openPicker(wrapper)
    const cells = dayCells()
    const today = cells.find((c) => c.id.includes(todayStr()))!
    expect(today.getAttribute('aria-current')).toBe('date')
    expect(today.getAttribute('aria-selected')).toBe('true')
    wrapper.unmount()
  })

  it('Esc 关闭后焦点归还触发按钮', async () => {
    const wrapper = mount(DatePicker, { props: { modelValue: '' }, attachTo: document.body })
    await openPicker(wrapper)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(wrapper.find('button.ui-select-trigger').element)
    wrapper.unmount()
  })
})
