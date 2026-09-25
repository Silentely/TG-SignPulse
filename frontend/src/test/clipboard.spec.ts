import { afterEach, describe, expect, it, vi } from 'vitest'
import { copyToClipboard } from '../lib/clipboard'

describe('copyToClipboard', () => {
  // createElement 等被 spy 的方法必须还原，否则后续用例二次 spy 会得到失效的实现
  afterEach(() => {
    vi.restoreAllMocks()
  })

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

  it('readonly 复制失败后回退到可写 textarea 重试（iOS 场景）', async () => {
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockRejectedValue(new Error('permission denied')),
      },
    })
    document.execCommand = vi
      .fn()
      .mockReturnValueOnce(false) // 第一次 readonly 失败
      .mockReturnValueOnce(true) // 第二次可写重试成功

    const readonlySeen: string[] = []
    const origCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      const el = origCreate(tag)
      if (tag === 'textarea') {
        const origSetAttr = el.setAttribute.bind(el)
        el.setAttribute = (name: string, val: string) => {
          if (name === 'readonly') readonlySeen.push(val)
          origSetAttr(name, val)
        }
      }
      return el
    })

    const result = await copyToClipboard('ios fallback text')
    expect(result).toBe(true)
    expect(document.execCommand).toHaveBeenCalledTimes(2)
    // 仅第一次尝试使用 readonly，重试时不再设置 readonly
    expect(readonlySeen).toEqual([''])
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })
})
