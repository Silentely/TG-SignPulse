import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  /** 可选多行详情 */
  description?: string
  type: 'success' | 'error' | 'info'
}

export interface ToastOptions {
  description?: string
  duration?: number
}

/** 同时展示的 toast 上限，超出时淘汰最早的条目 */
const MAX_TOASTS = 5

const toasts = ref<ToastItem[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let nextId = 0

function removeToast(id: number) {
  const timer = timers.get(id)
  if (timer !== undefined) {
    clearTimeout(timer)
    timers.delete(id)
  }
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
    toasts.value = []
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
  const info = (message: string, opts?: ToastOptions) =>
    show(message, 'info', opts ?? 4000)

  return { toasts, show, success, error, info, dismiss, clear }
}
