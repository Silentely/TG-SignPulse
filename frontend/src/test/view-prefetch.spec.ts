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
})
