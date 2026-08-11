import { describe, expect, it, vi, beforeEach } from 'vitest'

/**
 * i18n 与 <html lang> 同步回归：首帧初始化与运行时切换语言后，
 * documentElement.lang 必须与界面语言一致（屏读器/SEO 依赖）。
 */
describe('i18n html lang 同步', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('无语言偏好（默认中文）时设置 zh-CN', async () => {
    document.documentElement.lang = ''
    await import('../i18n')
    expect(document.documentElement.lang).toBe('zh-CN')
  })

  it('localStorage 存 en 时设置 en-US', async () => {
    localStorage.setItem('tg-signer-locale', 'en')
    document.documentElement.lang = ''
    await import('../i18n')
    expect(document.documentElement.lang).toBe('en-US')
  })

  it('localStorage 存 zh 时保持 zh-CN（非法值回落默认）', async () => {
    localStorage.setItem('tg-signer-locale', 'zh')
    document.documentElement.lang = 'en-US'
    await import('../i18n')
    expect(document.documentElement.lang).toBe('zh-CN')
  })
})
