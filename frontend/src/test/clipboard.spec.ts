import { describe, expect, it, vi } from 'vitest'
import { copyToClipboard } from '../lib/clipboard'

describe('copyToClipboard', () => {
  it('空文本返回 false', async () => {
    expect(await copyToClipboard('')).toBe(false)
  })

  it('使用 navigator.clipboard 成功复制', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, {
      clipboard: { writeText },
    })

    const result = await copyToClipboard('hello world')
    expect(result).toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello world')
  })

  it('navigator 复制异常降级到 execCommand', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('permission denied')),
      },
    })
    document.execCommand = vi.fn().mockReturnValue(true)

    let capturedReadonly = false
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const el = origCreate(tag)
      if (tag === "textarea") {
        const origSetAttr = el.setAttribute.bind(el)
        el.setAttribute = (name: string, val: string) => {
          if (name === "readonly") capturedReadonly = true
          origSetAttr(name, val)
        }
      }
      return el
    })

    const result = await copyToClipboard("fallback text")
    expect(capturedReadonly).toBe(true)
    expect(result).toBe(true)
    expect(document.execCommand).toHaveBeenCalledWith('copy')
  })

  it('execCommand 抛异常时也清理降级 textarea', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('permission denied')),
      },
    })
    document.execCommand = vi.fn().mockImplementation(() => {
      throw new Error('copy unavailable')
    })

    await expect(copyToClipboard('failure text')).resolves.toBe(false)
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })
})
