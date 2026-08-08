import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  /** 可选多行详情 */
  description?: string
  type: 'success' | 'error' | 'warning' | 'info'
}

export interface ToastOptions {
  description?: string
  duration?: number
}

/** 同时展示的 toast 上限，超出时淘汰最早的条目 */
const MAX_TOASTS = 5

const toasts = ref<ToastItem[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
/** 每个 toast 的绝对过期时间（用于暂停/恢复时计算剩余时长） */
const expiresAtMap = new Map<number, number>()
/** 暂停后剩余时长（毫秒）；resume 时据此重新计时 */
const remainingMap = new Map<number, number>()
let nextId = 0

function removeToast(id: number) {
  const timer = timers.get(id)
  if (timer !== undefined) {
    clearTimeout(timer)
    timers.delete(id)
  }
  expiresAtMap.delete(id)
  remainingMap.delete(id)
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export const useToast = () => {
  const dismiss = (id: number) => {
    removeToast(id)
  }

  const clear = () => {
    for (const timer of timers.values()) {
      clearTimeout(timer)
    }
    timers.clear()
    expiresAtMap.clear()
    remainingMap.clear()
    toasts.value = []
  }

  /**
   * 暂停指定 toast 的自动关闭倒计时（如鼠标悬停阅读长错误）。
   * 幂等：重复暂停不叠加。
   */
  const pause = (id: number) => {
    if (remainingMap.has(id)) return // 已暂停
    const timer = timers.get(id)
    const expiresAt = expiresAtMap.get(id)
    if (timer === undefined || expiresAt === undefined) return
    clearTimeout(timer)
    timers.delete(id)
    remainingMap.set(id, Math.max(0, expiresAt - Date.now()))
  }

  /**
   * 恢复指定 toast 的自动关闭倒计时，从暂停时剩余的时长继续。
   * 未暂停过或已消失的 toast 忽略。
   */
  const resume = (id: number) => {
    const remaining = remainingMap.get(id)
    if (remaining === undefined) return
    remainingMap.delete(id)
    if (remaining <= 0) {
      removeToast(id)
      return
    }
    const timer = setTimeout(() => {
      removeToast(id)
    }, remaining)
    timers.set(id, timer)
  }

  const show = (
    message: string,
    type: ToastItem['type'] = 'info',
    durationOrOpts: number | ToastOptions = 4000
  ) => {
    const text = String(message || '').trim()
    if (!text) return

    const opts: ToastOptions =
      typeof durationOrOpts === 'number'
        ? { duration: durationOrOpts }
        : durationOrOpts || {}
    const duration = opts.duration ?? (type === 'error' ? 5000 : 4000)

    while (toasts.value.length >= MAX_TOASTS) {
      const oldest = toasts.value[0]
      if (!oldest) break
      removeToast(oldest.id)
    }

    const id = nextId++
    toasts.value.push({
      id,
      message: text,
      description: opts.description?.trim() || undefined,
      type,
    })
    if (duration > 0) {
      expiresAtMap.set(id, Date.now() + duration)
      const timer = setTimeout(() => {
        removeToast(id)
      }, duration)
      timers.set(id, timer)
    }
  }

  const success = (message: string, opts?: ToastOptions) =>
    show(message, 'success', opts ?? 4000)
  const error = (message: string, opts?: ToastOptions) =>
    show(message, 'error', opts ?? { duration: 5000 })
  const warning = (message: string, opts?: ToastOptions) =>
    show(message, 'warning', opts ?? 4500)
  const info = (message: string, opts?: ToastOptions) =>
    show(message, 'info', opts ?? 4000)

  // show 仅为内部基底，不对外导出：业务统一走 success/error/warning/info 语义化入口
  return { toasts, success, error, warning, info, dismiss, clear, pause, resume }
}
