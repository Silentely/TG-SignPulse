/**
 * 账号列表：API → UI 映射与本地筛选（纯函数）。
 */
import type { AccountInfo } from './api'
import type { AccountUiItem } from './types'

export type AccountMapLabels = {
  loginExpired: string
  checking: string
}

/** 服务端账号 → 列表行字段（不含头像 blob） */
export function mapAccountInfoToUiItem(
  acc: AccountInfo,
  labels: AccountMapLabels,
): AccountUiItem {
  let uiStatus = 'active'
  let message = ''

  if (acc.needs_relogin || acc.status === 'invalid') {
    uiStatus = 'error'
    message = labels.loginExpired
  } else if (acc.status === 'error') {
    uiStatus = 'error'
    message = acc.status_message || ''
  } else if (acc.status === 'checking') {
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
