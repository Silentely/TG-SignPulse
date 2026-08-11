import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

/**
 * useTheme 主题色同步回归：theme-color meta 必须跟随实际主题
 * （含初始加载与运行时切换），保证浏览器标签栏/地址栏颜色一致。
 */
describe('useTheme theme-color 同步', () => {
  // jsdom 不实现 matchMedia，useTheme 模块加载时会读取系统偏好，需 stub
  const stubMatchMedia = (matches: boolean) => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      configurable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
  }

  const themeColorMeta = () =>
    document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')

  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    document.documentElement.classList.remove('dark')
    document.head.insertAdjacentHTML(
      'beforeend',
      '<meta name="theme-color" content="#ffffff" />',
    )
  })

  afterEach(() => {
    themeColorMeta()?.remove()
  })

  it('浅色默认时 theme-color 为浅色值', async () => {
    stubMatchMedia(false)
    const { useTheme } = await import('../composables/useTheme')
    useTheme()
    expect(themeColorMeta()?.getAttribute('content')).toBe('#ffffff')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('系统深色偏好时 theme-color 为深色值并添加 dark class', async () => {
    stubMatchMedia(true)
    const { useTheme } = await import('../composables/useTheme')
    useTheme()
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(themeColorMeta()?.getAttribute('content')).toBe('#0f172a')
  })

  it('toggleTheme 切换后同步 theme-color', async () => {
    stubMatchMedia(false)
    const { useTheme } = await import('../composables/useTheme')
    const { toggleTheme } = useTheme()
    toggleTheme()
    expect(themeColorMeta()?.getAttribute('content')).toBe('#0f172a')
    toggleTheme()
    expect(themeColorMeta()?.getAttribute('content')).toBe('#ffffff')
  })
})
