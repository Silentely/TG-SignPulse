/**
 * useEscClose：Esc 监听生命周期的守卫与卸载清理。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { useEscClose } from '../composables/useEscClose'

/** 测试宿主：把 active / 关闭动作接到组件状态上，便于断言回调是否触发 */
const makeHost = (active: () => boolean, onEsc: () => void) =>
  defineComponent({
    setup() {
      useEscClose(active, onEsc)
      return () => h('div')
    },
  })

const esc = () =>
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))

describe('useEscClose', () => {
  it('active 为 true 时触发回调并阻止默认行为', async () => {
    const onEsc = vi.fn()
    const wrapper = mount(makeHost(() => true, onEsc))
    const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(ev)
    expect(onEsc).toHaveBeenCalledTimes(1)
    expect(ev.defaultPrevented).toBe(true)
    wrapper.unmount()
  })

  it('active 为 false 时静默忽略，不冒泡也不回调', async () => {
    const onEsc = vi.fn()
    const wrapper = mount(makeHost(() => false, onEsc))
    esc()
    expect(onEsc).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('非 Esc 按键不触发回调', async () => {
    const onEsc = vi.fn()
    const wrapper = mount(makeHost(() => true, onEsc))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    expect(onEsc).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('canClose 返回 false 时不回调（嵌套弹窗把 Esc 交给上层）', async () => {
    const onEsc = vi.fn()
    const wrapper = mount(
      defineComponent({
        setup() {
          useEscClose(() => true, onEsc, { canClose: () => false })
          return () => h('div')
        },
      }),
    )
    esc()
    expect(onEsc).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('不擅自阻断事件：window 上的其它监听器（如下层弹窗）仍会收到 Esc', () => {
    // window 是冒泡路径最后一环，且同节点监听器不受 stopPropagation 影响；
    // 下层弹窗靠自己的 canClose 守卫退出，而不是依赖事件被吞掉
    const otherWindowListener = vi.fn()
    window.addEventListener('keydown', otherWindowListener)
    const wrapper = mount(makeHost(() => true, () => {}))
    esc()
    expect(otherWindowListener).toHaveBeenCalledTimes(1)
    window.removeEventListener('keydown', otherWindowListener)
    wrapper.unmount()
  })

  it('卸载后不再响应 Esc（监听器已移除）', async () => {
    const onEsc = vi.fn()
    const wrapper = mount(makeHost(() => true, onEsc))
    wrapper.unmount()
    await nextTick()
    esc()
    expect(onEsc).not.toHaveBeenCalled()
  })

  it('接受 ref 形式的活动状态，并随其变化实时生效', async () => {
    const onEsc = vi.fn()
    const open = ref(false)
    const wrapper = mount(
      defineComponent({
        setup() {
          useEscClose(open, onEsc)
          return () => h('div')
        },
      }),
    )
    esc()
    expect(onEsc).not.toHaveBeenCalled()
    open.value = true
    await nextTick()
    esc()
    expect(onEsc).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
