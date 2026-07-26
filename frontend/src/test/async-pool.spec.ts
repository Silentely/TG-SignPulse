import { describe, expect, it, vi } from 'vitest'
import { mapPool } from '../lib/async-pool'

describe('mapPool', () => {
  it('空列表返回空结果', async () => {
    const results = await mapPool([], 4, async () => 1)
    expect(results).toEqual([])
  })

  it('保持输入顺序且限制并发', async () => {
    let inFlight = 0
    let maxInFlight = 0
    const items = [1, 2, 3, 4, 5, 6]
    const results = await mapPool(items, 2, async (n) => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      await new Promise((r) => setTimeout(r, 20))
      inFlight -= 1
      return n * 10
    })
    expect(maxInFlight).toBeLessThanOrEqual(2)
    expect(results.map((r) => (r.status === 'fulfilled' ? r.value : null))).toEqual([
      10, 20, 30, 40, 50, 60,
    ])
  })

  it('单任务失败不影响其他任务', async () => {
    const results = await mapPool([1, 2, 3], 2, async (n) => {
      if (n === 2) throw new Error('boom')
      return n
    })
    expect(results[0]).toEqual({ status: 'fulfilled', value: 1 })
    expect(results[1].status).toBe('rejected')
    expect(results[2]).toEqual({ status: 'fulfilled', value: 3 })
  })

  it('concurrency 小于 1 时按 1 处理', async () => {
    const spy = vi.fn(async (n: number) => n)
    await mapPool([1, 2], 0, spy)
    expect(spy).toHaveBeenCalledTimes(2)
  })
})
