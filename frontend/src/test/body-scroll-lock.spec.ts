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
    const { lockBodyScroll, unlockBodyScroll } = await import('../lib/body-scroll-lock')

    lockBodyScroll()
    expect(document.body.style.overflow).toBe('hidden')

    lockBodyScroll()
    expect(document.body.style.overflow).toBe('hidden')

    unlockBodyScroll()
    expect(document.body.style.overflow).toBe('hidden')

    unlockBodyScroll()
    expect(document.body.style.overflow).toBe('')
  })

  it('unlock 不会减到负数', async () => {
    const { lockBodyScroll, unlockBodyScroll } = await import('../lib/body-scroll-lock')
    // 若计数被减到负数，后续 lock 时计数仍 <=0，不会重新隐藏
    lockBodyScroll()
    unlockBodyScroll()
    unlockBodyScroll()
    expect(document.body.style.overflow).toBe('')
    lockBodyScroll()
    expect(document.body.style.overflow).toBe('hidden')
  })
})
