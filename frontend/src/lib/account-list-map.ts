/**
 * 账号列表：API → UI 映射与本地筛选（纯函数）。
 */
import type { AccountInfo } from './api'
import type { AccountUiItem } from './types'

export type AccountMapLabels = {
  loginExpired: string
  checking: string
}

export type AccountHealthState =
  | 'healthy'
  | 'checking'
  | 'relogin'
  | 'retry'
  | 'unknown'

/**
 * 账号健康分类：仪表盘健康卡与账号列表共用同一套判定。
 *
 * - relogin：会话/凭据失效，需要重新登录
 * - retry：代理拦截、网络或临时错误，稍后重试即可，不引导重登
 */
export function classifyAccountHealth(
  acc: Pick<AccountInfo, 'status' | 'needs_relogin'>,
): AccountHealthState {
  if (acc.needs_relogin || acc.status === 'invalid' || acc.status === 'not_found') {
    return 'relogin'
  }
  if (acc.status === 'blocked' || acc.status === 'error') {
    return 'retry'
  }
  if (acc.status === 'connected') return 'healthy'
  if (acc.status === 'checking') return 'checking'
  return 'unknown'
}

/** 服务端账号 → 列表行字段（不含头像 blob） */
export function mapAccountInfoToUiItem(
  acc: AccountInfo,
  labels: AccountMapLabels,
): AccountUiItem {
  const health = classifyAccountHealth(acc)
  let uiStatus = 'active'
  let message = ''

  if (health === 'relogin') {
    uiStatus = 'error'
    message = labels.loginExpired
  } else if (health === 'retry') {
    uiStatus = 'error'
    message = acc.status_message || ''
  } else if (health === 'checking') {
    uiStatus = 'empty'
    message = labels.checking
  } else if (
    acc.status_message?.includes('流量') ||
    acc.status_message?.includes('额度')
  ) {
    uiStatus = 'empty'
    message = acc.status_message
  }

  return {
    id: acc.name,
    name: acc.name,
    remark: acc.remark,
    status: uiStatus,
    message,
    avatarUrl: '',
    raw: acc,
  }
}

export function filterAccountsByQuery<
  T extends { name: string; remark?: string | null; message?: string | null },
>(accounts: T[], searchQuery: string): T[] {
  const q = searchQuery.trim().toLowerCase()
  if (!q) return accounts
  return accounts.filter(
    (a) =>
      a.name.toLowerCase().includes(q) ||
      (a.remark || '').toLowerCase().includes(q) ||
      (a.message || '').toLowerCase().includes(q),
  )
}

export function compareAccountNames(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" })
}
