import { describe, it, expect, beforeEach, vi } from 'vitest'

describe('useCommandPalette', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('toggle 打开与关闭', async () => {
    const { useCommandPalette } = await import('../composables/useCommandPalette')
    const { isOpen, show, hide, toggle, search } = useCommandPalette()
    expect(isOpen.value).toBe(false)
    show()
    expect(isOpen.value).toBe(true)
    search.value = 'acc'
    hide()
    expect(isOpen.value).toBe(false)
    expect(search.value).toBe('')
    toggle()
    expect(isOpen.value).toBe(true)
    toggle()
    expect(isOpen.value).toBe(false)
  })
})
