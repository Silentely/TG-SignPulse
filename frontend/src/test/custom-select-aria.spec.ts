/**
 * CustomSelect/MultiSelect 键盘漫游的读屏播报链路：
 * 触发按钮持有焦点，方向键漫游通过 aria-activedescendant 指向当前项，
 * 且 aria-controls 关联 listbox；option 需有稳定 id。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import CustomSelect from '../components/CustomSelect.vue'
import MultiSelect from '../components/MultiSelect.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const OPTIONS = [
  { label: '甲', value: 'a' },
  { label: '乙', value: 'b' },
]

const keydown = async (el: Element, key: string) => {
  el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  await new Promise((r) => setTimeout(r, 0))
}

describe('Select aria-activedescendant', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    // jsdom 未实现 scrollIntoView，键盘漫游会触发组件滚动跟随，打桩即可
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('CustomSelect 打开后 aria-controls 指向 listbox，漫游更新 activedescendant', async () => {
    const wrapper = mount(CustomSelect, {
      props: { modelValue: 'a', options: OPTIONS },
      attachTo: document.body,
    })
    const trigger = wrapper.find('button.ui-select-trigger')
    await keydown(trigger.element, 'ArrowDown')

    const listbox = document.body.querySelector('[role="listbox"]')
    expect(listbox).toBeTruthy()
    expect(trigger.attributes('aria-controls')).toBe(listbox!.id)

    // 打开时高亮当前选中项（甲=a），漫游到下一项（乙=b）
    const first = document.body.querySelectorAll('[role="option"]')[0] as HTMLElement
    expect(trigger.attributes('aria-activedescendant')).toBe(first.id)

    await keydown(trigger.element, 'ArrowDown')
    const second = document.body.querySelectorAll('[role="option"]')[1] as HTMLElement
    expect(trigger.attributes('aria-activedescendant')).toBe(second.id)
    wrapper.unmount()
  })

  it('CustomSelect 关闭后 activedescendant 与 controls 移除', async () => {
    const wrapper = mount(CustomSelect, {
      props: { modelValue: 'a', options: OPTIONS },
      attachTo: document.body,
    })
    const trigger = wrapper.find('button.ui-select-trigger')
    await keydown(trigger.element, 'ArrowDown')
    await keydown(trigger.element, 'Escape')
    expect(trigger.attributes('aria-activedescendant')).toBeUndefined()
    expect(trigger.attributes('aria-controls')).toBeUndefined()
    wrapper.unmount()
  })

  it('MultiSelect 漫游位 -1 指向「全部账号」项，下移后指向首个账号', async () => {
    const wrapper = mount(MultiSelect, {
      props: { modelValue: [] as string[], options: OPTIONS },
      attachTo: document.body,
    })
    const trigger = wrapper.find('button.ui-select-trigger')
    await keydown(trigger.element, 'ArrowDown')

    const listbox = document.body.querySelector('[role="listbox"]')
    expect(listbox).toBeTruthy()
    expect(trigger.attributes('aria-controls')).toBe(listbox!.id)

    const opts = document.body.querySelectorAll('[role="option"]')
    expect(opts.length).toBe(OPTIONS.length + 1)
    // 初始漫游位 -1 = 「全部账号」首项
    expect(trigger.attributes('aria-activedescendant')).toBe((opts[0] as HTMLElement).id)

    await keydown(trigger.element, 'ArrowDown')
    expect(trigger.attributes('aria-activedescendant')).toBe((opts[1] as HTMLElement).id)
    wrapper.unmount()
  })
})
