import { afterEach, describe, expect, it, vi } from 'vitest'
import { startChainPoll } from '../lib/chain-poll'

describe('startChainPoll', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('立即执行第一轮，结束后再按间隔续跑', async () => {
    vi.useFakeTimers()
    const tick = vi.fn(async () => {
      await Promise.resolve()
    })
    const handle = startChainPoll(tick, { intervalMs: 1000 })
    // 同步启动 run，需 flush microtask
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(2)
    handle.stop()
    await vi.advanceTimersByTimeAsync(2000)
    expect(tick).toHaveBeenCalledTimes(2)
  })

  it('runImmediately=false 时先等间隔', async () => {
    vi.useFakeTimers()
    const tick = vi.fn(async () => {})
    const handle = startChainPoll(tick, { intervalMs: 500, runImmediately: false })
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(0)
    await vi.advanceTimersByTimeAsync(500)
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(1)
    handle.stop()
  })

  it('tick 抛错后仍继续调度', async () => {
    vi.useFakeTimers()
    let n = 0
    const tick = vi.fn(async () => {
      n += 1
      if (n === 1) throw new Error('boom')
    })
    const handle = startChainPoll(tick, { intervalMs: 200 })
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(200)
    await Promise.resolve()
    expect(tick).toHaveBeenCalledTimes(2)
    handle.stop()
  })

  it('stop 后 active 为 false', () => {
    const handle = startChainPoll(async () => {}, { intervalMs: 1000 })
    expect(handle.active).toBe(true)
    handle.stop()
    expect(handle.active).toBe(false)
  })
})
