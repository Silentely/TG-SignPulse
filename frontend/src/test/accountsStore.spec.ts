import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
}))

vi.mock('../lib/api', () => api)

import { useAccountsStore } from '../stores/accounts'
import { useAuthStore } from '../stores/auth'

describe('accountsStore', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    useAuthStore().setToken('tok')
    api.listAccounts.mockResolvedValue({
      accounts: [{ name: 'a1' }, { name: 'a2' }],
      total: 2,
    })
  })

  it('首次 ensureAccounts 拉取并缓存列表', async () => {
    const store = useAccountsStore()
    const list = await store.ensureAccounts()
    expect(api.listAccounts).toHaveBeenCalledTimes(1)
    expect(list.map((a) => a.name)).toEqual(['a1', 'a2'])
    expect(store.accounts).toHaveLength(2)
    expect(store.total).toBe(2)
    expect(store.fetchedAt).toBeGreaterThan(0)
    expect(store.loading).toBe(false)
  })

  it('TTL 内重复 ensure 复用缓存，不重复请求', async () => {
    const store = useAccountsStore()
    await store.ensureAccounts()
    await store.ensureAccounts()
    expect(api.listAccounts).toHaveBeenCalledTimes(1)
  })

  it('TTL 过期后 ensure 重新拉取', async () => {
    vi.useFakeTimers()
    const store = useAccountsStore()
    await store.ensureAccounts()
    // 越过 30s TTL
    vi.setSystemTime(Date.now() + 31_000)
    await store.ensureAccounts()
    expect(api.listAccounts).toHaveBeenCalledTimes(2)
  })

  it('refreshAccounts 强制刷新（绕过 TTL）', async () => {
    const store = useAccountsStore()
    await store.ensureAccounts()
    await store.refreshAccounts()
    expect(api.listAccounts).toHaveBeenCalledTimes(2)
  })

  it('并发请求去重：同刻只有一次真实请求，且结果一致', async () => {
    let resolveReq!: (v: { accounts: Array<{ name: string }>; total: number }) => void
    api.listAccounts.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveReq = resolve
      }),
    )
    const store = useAccountsStore()
    const p1 = store.ensureAccounts()
    const p2 = store.ensureAccounts()
    resolveReq({ accounts: [{ name: 'only' }], total: 1 })
    const [l1, l2] = await Promise.all([p1, p2])
    expect(api.listAccounts).toHaveBeenCalledTimes(1)
    expect(l1).toBe(l2)
    expect(store.accounts.map((a) => a.name)).toEqual(['only'])
  })

  it('refreshAccounts 等待在途请求落地后再强制拉新，不搭陈旧响应的车', async () => {
    let resolveReq!: (v: { accounts: Array<{ name: string }>; total: number }) => void
    api.listAccounts
      .mockReturnValueOnce(
        new Promise((resolve) => {
          resolveReq = resolve
        }),
      )
      .mockResolvedValueOnce({ accounts: [{ name: 'fresh' }], total: 1 })
    const store = useAccountsStore()
    // 在途请求拉取于"写操作完成之前"（数据陈旧）
    const stale = store.ensureAccounts()
    const fresh = store.refreshAccounts()
    resolveReq({ accounts: [{ name: 'stale' }], total: 1 })
    const [s, f] = await Promise.all([stale, fresh])
    expect(api.listAccounts).toHaveBeenCalledTimes(2)
    expect(s.map((a) => a.name)).toEqual(['stale'])
    expect(f.map((a) => a.name)).toEqual(['fresh'])
    expect(store.accounts.map((a) => a.name)).toEqual(['fresh'])
  })

  it('token 清空时同步清空缓存，防止跨会话残留', async () => {
    const store = useAccountsStore()
    await store.ensureAccounts()
    expect(store.fetchedAt).toBeGreaterThan(0)
    useAuthStore().clearToken()
    expect(store.accounts).toEqual([])
    expect(store.total).toBe(0)
    expect(store.fetchedAt).toBe(0)
  })

  it('无 token 时不发起请求', async () => {
    useAuthStore().clearToken()
    const store = useAccountsStore()
    const list = await store.ensureAccounts()
    expect(api.listAccounts).not.toHaveBeenCalled()
    expect(list).toEqual([])
  })

  it('失败透传且不写入缓存时间戳，立即重试可成功', async () => {
    api.listAccounts.mockRejectedValueOnce(new Error('boom'))
    const store = useAccountsStore()
    await expect(store.ensureAccounts()).rejects.toThrow('boom')
    expect(store.fetchedAt).toBe(0)
    // 失败不进 TTL 缓存，立即可重试
    await store.ensureAccounts()
    expect(api.listAccounts).toHaveBeenCalledTimes(2)
    expect(store.accounts).toHaveLength(2)
  })
})
