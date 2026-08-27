/**
 * activeRuns store 轮询生命周期回归：
 * acquire 的 refresh 在途期间 release 到 0 时，回调不得再启动轮询（永久泄漏）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  listActiveSignTaskRuns: vi.fn(),
}))
const pollSpy = vi.hoisted(() => ({
  startChainPoll: vi.fn(() => ({ stop: vi.fn(), get active() { return true } })),
}))

vi.mock('../lib/api', () => api)
vi.mock('../lib/chain-poll', () => ({ startChainPoll: pollSpy.startChainPoll }))

import { useAuthStore } from '../stores/auth'

async function freshStore() {
  vi.resetModules()
  const mod = await import('../stores/activeRuns')
  return mod.useActiveRunsStore()
}

describe('activeRunsStore 轮询生命周期', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore().setToken('tok')
  })

  it('acquire 后 refresh 完成且有活跃 run 时启动轮询', async () => {
    api.listActiveSignTaskRuns.mockResolvedValue({
      runs: [{ task_name: 't1', account_name: 'a1', state: 'running', run_id: 'r1' }],
    })
    const store = await freshStore()
    store.acquire()
    await vi.waitFor(() => {
      expect(pollSpy.startChainPoll).toHaveBeenCalled()
    })
    store.release()
  })

  it('refresh 在途期间 release 到 0：回调不再启动轮询', async () => {
    let resolveRefresh: (v: unknown) => void = () => {}
    api.listActiveSignTaskRuns.mockImplementation(
      () => new Promise((res) => { resolveRefresh = res }),
    )
    const store = await freshStore()
    store.acquire()
    store.release()
    resolveRefresh({ runs: [{ task_name: 't1', account_name: 'a1', state: 'running', run_id: 'r1' }] })
    await new Promise((r) => setTimeout(r, 20))
    expect(pollSpy.startChainPoll).not.toHaveBeenCalled()
  })
})
