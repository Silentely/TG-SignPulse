import { describe, expect, it, vi } from 'vitest'
import { createViewPrefetcher } from '../lib/view-prefetch'

describe('页面预加载', () => {
  it('同一页面只加载一次，并消费 loader rejection', async () => {
    const loader = vi.fn(() => Promise.reject(new Error('chunk failed')))
    const warn = vi.fn()
    const { prefetch } = createViewPrefetcher({ page: loader }, { warn })

    prefetch('page')
    prefetch('page')
    await Promise.resolve()

    expect(loader).toHaveBeenCalledTimes(1)
    expect(warn).toHaveBeenCalledWith('page', expect.any(Error))
  })

  it('预加载失败后允许后续重试', async () => {
    const loader = vi.fn()
      .mockImplementationOnce(() => Promise.reject(new Error('offline')))
      .mockImplementationOnce(() => Promise.resolve({}))
    const warn = vi.fn()
    const { prefetch } = createViewPrefetcher({ page: loader }, { warn })

    prefetch('page')
    await Promise.resolve()
    expect(loader).toHaveBeenCalledTimes(1)

    prefetch('page')
    await Promise.resolve()
    expect(loader).toHaveBeenCalledTimes(2)
    expect(warn).toHaveBeenCalledTimes(1)
  })

  it('warmup 会加载全部视图且不重复', async () => {
    const loaders = {
      a: vi.fn(() => Promise.resolve({})),
      b: vi.fn(() => Promise.resolve({})),
    }
    const { warmup } = createViewPrefetcher(loaders)

    warmup()
    warmup()
    await Promise.resolve()

    expect(loaders.a).toHaveBeenCalledTimes(1)
    expect(loaders.b).toHaveBeenCalledTimes(1)
  })
})
