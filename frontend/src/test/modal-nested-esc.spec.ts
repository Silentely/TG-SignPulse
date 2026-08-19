/**
 * Modal 嵌套 Esc 关闭语义测试：
 * 确认框叠在业务弹窗上时，Esc 只关闭最顶层弹窗；
 * 顶层关闭后，下层弹窗恢复 Esc 响应权。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import Modal from '../components/Modal.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const emitKeydown = (key: string) => {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
}

describe('Modal nested Esc', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('独立弹窗 Esc 正常关闭', async () => {
    const wrapper = mount(Modal, {
      props: { title: 'T', isOpen: true },
    })
    emitKeydown('Escape')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('close')).toBeTruthy()
    wrapper.unmount()
  })

  it('嵌套时 Esc 只关最顶层，顶层关闭后下层恢复响应', async () => {
    // 业务弹窗
    const outer = mount(Modal, {
      props: { title: 'outer', isOpen: true },
    })
    // 确认框叠在上面
    const inner = mount(Modal, {
      props: { title: 'inner', isOpen: true },
    })

    emitKeydown('Escape')
    await Promise.all([outer.vm.$nextTick(), inner.vm.$nextTick()])
    // 只有最顶层（inner）收到 close
    expect(inner.emitted('close')).toBeTruthy()
    expect(outer.emitted('close')).toBeFalsy()

    // 父组件响应关闭：内层 isOpen 置 false，释放顶层标识
    await inner.setProps({ isOpen: false })
    emitKeydown('Escape')
    await outer.vm.$nextTick()
    expect(outer.emitted('close')).toBeTruthy()

    outer.unmount()
    inner.unmount()
  })
})
