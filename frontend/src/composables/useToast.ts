import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  type: 'success' | 'error' | 'info'
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

  const show = (message: string, type: ToastItem['type'] = 'info', duration = 4000) => {
    const text = String(message || '').trim()
    if (!text) return

    // 超出上限时淘汰最早条目
    while (toasts.value.length >= MAX_TOASTS) {
      const oldest = toasts.value[0]
      if (!oldest) break
      removeToast(oldest.id)
    }

    const id = nextId++
    toasts.value.push({ id, message: text, type })
    if (duration > 0) {
      const timer = setTimeout(() => {
        removeToast(id)
      }, duration)
      timers.set(id, timer)
    }
  }

  const success = (message: string) => show(message, 'success')
  const error = (message: string) => show(message, 'error', 5000)
  const info = (message: string) => show(message, 'info')

  return { toasts, show, success, error, info, dismiss, clear }
}
