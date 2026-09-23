/**
 * Esc 关闭的窗口监听生命周期收拢。
 *
 * 弹窗（Modal）、日期面板、模板菜单都遵循同一约定：监听 window keydown，
 * 仅在「处于打开状态」时响应 Esc，其余情况把按键交给上层处理。
 *
 * 各组件自行决定打开状态的判定与关闭动作；composable 只负责
 * 注册 / 卸载注销与守卫编排，避免每处重写一遍 add/removeEventListener 对。
 *
 * 说明：此处刻意不提供 stopPropagation。window 是冒泡路径的最后一环，
 * 同节点上的其它监听器（如下层弹窗）也不受 stopPropagation 影响——
 * 真正需要「Esc 只关最上层」时请用 canClose 守卫；
 * 需要阻断 Esc 传到 window（下拉收起时不关整个弹窗）应在元素级 @keydown 里处理。
 */
import { onUnmounted, type Ref } from 'vue'

export interface EscCloseOptions {
  /** 额外守卫返回 false 时把 Esc 交给上层（如嵌套弹窗的「仅最顶层响应」判定） */
  canClose?: () => boolean
}

export function useEscClose(
  active: Ref<boolean> | (() => boolean),
  onEsc: (e: KeyboardEvent) => void,
  options: EscCloseOptions = {},
): void {
  const isActive = () => (typeof active === 'function' ? active() : active.value)

  const onKeydown = (e: KeyboardEvent) => {
    if (e.key !== 'Escape') return
    if (!isActive()) return
    if (options.canClose && !options.canClose()) return
    // Esc 无需要保留的浏览器默认行为，统一阻止以防输入法等消费该键
    e.preventDefault()
    onEsc(e)
  }

  window.addEventListener('keydown', onKeydown)
  onUnmounted(() => window.removeEventListener('keydown', onKeydown))
}
