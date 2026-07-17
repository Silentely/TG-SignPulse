/**
 * 引用计数式 body 滚动锁。
 * 多个 Modal / 命令面板 / 抽屉同时打开时，避免后关的一个把 overflow 清掉。
 */
let lockCount = 0

export function lockBodyScroll(): void {
  if (typeof document === 'undefined') return
  lockCount += 1
  if (lockCount === 1) {
    document.body.style.overflow = 'hidden'
  }
}

export function unlockBodyScroll(): void {
  if (typeof document === 'undefined') return
  lockCount = Math.max(0, lockCount - 1)
  if (lockCount === 0) {
    document.body.style.overflow = ''
  }
}

/** 测试或强制恢复用 */
export function resetBodyScrollLock(): void {
  lockCount = 0
  if (typeof document !== 'undefined') {
    document.body.style.overflow = ''
  }
}

export function getBodyScrollLockCount(): number {
  return lockCount
}
