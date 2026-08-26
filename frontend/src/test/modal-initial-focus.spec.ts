/**
 * Modal 打开时的首焦点位置：优先落在表单首个输入框，
 * 而非 header 的关闭按钮；无表单字段时回退到首个可聚焦元素。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import Modal from '../components/Modal.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

describe('Modal 初始焦点', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('含输入框时首焦点落在输入框', async () => {
    const wrapper = mount(Modal, {
      props: { title: 'T', isOpen: true },
      slots: { default: '<input id="f" type="text" /><button>ok</button>' },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()
    expect(document.activeElement?.tagName).toBe('INPUT')
    wrapper.unmount()
  })

  it('无表单字段时回退到首个可聚焦元素（关闭按钮）', async () => {
    const wrapper = mount(Modal, {
      props: { title: 'T', isOpen: true },
      slots: { default: '<p>文本</p>' },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()
    const el = document.activeElement as HTMLElement
    expect(el?.getAttribute('aria-label')).toBe('common.close')
    wrapper.unmount()
  })

  it('隐藏/勾选类控件不应抢占首焦点', async () => {
    const wrapper = mount(Modal, {
      props: { title: 'T', isOpen: true },
      slots: {
        default:
          '<input type="checkbox" id="cb" /><input type="hidden" /><textarea id="ta"></textarea>',
      },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()
    expect((document.activeElement as HTMLElement)?.id).toBe('ta')
    wrapper.unmount()
  })
})
