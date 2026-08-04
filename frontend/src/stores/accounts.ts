/**
 * 跨页面共享的账号列表状态。
 * Accounts / Tasks / Logs / Dashboard 原来各自持有本地 ref 并独立调 listAccounts，
 * 统一收敛到此 store：TTL 缓存 + 并发请求去重，避免页面切换重复拉取。
 */
import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { listAccounts, type AccountInfo } from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import { useAuthStore } from './auth'

/** TTL 内 ensureAccounts 直接复用缓存 */
const ACCOUNTS_TTL_MS = 30_000

export const useAccountsStore = defineStore('accounts', () => {
  const accounts = ref<AccountInfo[]>([])
  const total = ref(0)
  const loading = ref(false)
  /** 最近一次成功拉取时间（epoch ms），0 = 从未成功 */
  const fetchedAt = ref(0)
  /** 同刻只允许一次真实请求，后来者复用同一 Promise */
  let inFlight: Promise<AccountInfo[]> | null = null

  /** 会话失效（登出/token 清空）时同步清空缓存，避免跨会话残留上一租户的列表 */
  watch(
    () => useAuthStore().token,
    (token) => {
      if (token) return
      accounts.value = []
      total.value = 0
      fetchedAt.value = 0
    },
    // flush: 'sync' —— store 内 watch 不挂在组件树上，pre 队列时机不可靠
    { flush: 'sync' },
  )

  const fetchAccounts = async (): Promise<AccountInfo[]> => {
    const token = getAuthToken()
    if (!token) return accounts.value
    loading.value = true
    try {
      const res = await listAccounts(token)
      accounts.value = res.accounts || []
      total.value = res.total ?? accounts.value.length
      fetchedAt.value = Date.now()
      return accounts.value
    } finally {
      loading.value = false
    }
  }

  /** ensure 语义：TTL 命中返回缓存，force 跳过 TTL；并发去重。失败透传给调用方（不缓存失败） */
  const ensureAccounts = (force = false): Promise<AccountInfo[]> => {
    if (!force && fetchedAt.value > 0 && Date.now() - fetchedAt.value < ACCOUNTS_TTL_MS) {
      return Promise.resolve(accounts.value)
    }
    if (!inFlight) {
      inFlight = fetchAccounts().finally(() => {
        inFlight = null
      })
    }
    return inFlight
  }

  /**
   * 账号增删改成功后强制刷新。
   * 若有在途请求（其数据拉取于写操作完成前），先等它落地再强制拉新，
   * 避免陈旧响应被盖戳为新缓存。
   */
  const refreshAccounts = async (): Promise<AccountInfo[]> => {
    if (inFlight) await inFlight.catch(() => {})
    return ensureAccounts(true)
  }

  return { accounts, total, loading, fetchedAt, ensureAccounts, refreshAccounts }
})
