import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

describe('body-scroll-lock', () => {
  beforeEach(() => {
    vi.resetModules()
    document.body.style.overflow = ''
  })

  afterEach(async () => {
    const { resetBodyScrollLock } = await import('../lib/body-scroll-lock')
    resetBodyScrollLock()
  })

  it('嵌套 lock 后仅最外层 unlock 才恢复滚动', async () => {
    const { lockBodyScroll, unlockBodyScroll, getBodyScrollLockCount } =
      await import('../lib/body-scroll-lock')

    lockBodyScroll()
    expect(document.body.style.overflow).toBe('hidden')
    expect(getBodyScrollLockCount()).toBe(1)

    lockBodyScroll()
    expect(getBodyScrollLockCount()).toBe(2)
    expect(document.body.style.overflow).toBe('hidden')

    unlockBodyScroll()
    expect(getBodyScrollLockCount()).toBe(1)
    expect(document.body.style.overflow).toBe('hidden')

    unlockBodyScroll()
    expect(getBodyScrollLockCount()).toBe(0)
    expect(document.body.style.overflow).toBe('')
  })

  it('unlock 不会减到负数', async () => {
    const { unlockBodyScroll, getBodyScrollLockCount } =
      await import('../lib/body-scroll-lock')
    unlockBodyScroll()
    unlockBodyScroll()
    expect(getBodyScrollLockCount()).toBe(0)
  })
})
