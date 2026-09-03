/**
 * 安全剪贴板复制封装：
 * 优先调用 navigator.clipboard.writeText，在非 HTTPS 或不支持的环境降级为 textarea + execCommand。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false

  if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 降级尝试
    }
  }

  if (typeof document !== 'undefined') {
    let textarea: HTMLTextAreaElement | null = null
    try {
      textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.left = '-9999px'
      textarea.style.top = '-9999px'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.focus()
      textarea.select()
      const success = document.execCommand('copy')
      return success
    } catch {
      return false
    } finally {
      textarea?.remove()
    }
  }

  return false
}
