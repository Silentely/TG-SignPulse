import { describe, it, expect } from 'vitest'
import {
  classifyAccountHealth,
  compareAccountNames,
  filterAccountsByQuery,
  mapAccountInfoToUiItem,
} from '../lib/account-list-map'
import type { AccountInfo } from '../lib/api'

const labels = { loginExpired: '登录失效', checking: '检测中' }

describe('account-list-map', () => {
  it('maps invalid and checking statuses', () => {
    const invalid = mapAccountInfoToUiItem(
      { name: 'a', needs_relogin: true, status: 'invalid' } as AccountInfo,
      labels,
    )
    expect(invalid.status).toBe('error')
    expect(invalid.message).toBe('登录失效')

    const checking = mapAccountInfoToUiItem(
      { name: 'b', status: 'checking' } as AccountInfo,
      labels,
    )
    expect(checking.status).toBe('empty')
    expect(checking.message).toBe('检测中')
  })

  it('classifies blocked and not_found as abnormal', () => {
    expect(classifyAccountHealth({ status: 'connected' } as AccountInfo)).toBe('healthy')
    expect(classifyAccountHealth({ status: 'checking' } as AccountInfo)).toBe('checking')
    expect(
      classifyAccountHealth({ status: 'blocked', needs_relogin: false } as AccountInfo),
    ).toBe('retry')
    expect(classifyAccountHealth({ status: 'error' } as AccountInfo)).toBe('retry')
    expect(classifyAccountHealth({ status: 'not_found' } as AccountInfo)).toBe('relogin')
    expect(
      classifyAccountHealth({ status: 'invalid', needs_relogin: true } as AccountInfo),
    ).toBe('relogin')
    // 代理拦截但凭据不匹配：重登优先于重试
    expect(
      classifyAccountHealth({ status: 'blocked', needs_relogin: true } as AccountInfo),
    ).toBe('relogin')
  })

  it('maps blocked accounts to the error state with their message', () => {
    const blocked = mapAccountInfoToUiItem(
      {
        name: 'c',
        status: 'blocked',
        status_message: 'PROXY_BLOCKED',
        needs_relogin: false,
      } as AccountInfo,
      labels,
    )
    expect(blocked.status).toBe('error')
    expect(blocked.message).toBe('PROXY_BLOCKED')
  })

  it('filters by name remark message', () => {
    const list = [
      { name: 'alice', remark: '主号', message: '' },
      { name: 'bob', remark: '', message: '额度不足' },
    ]
    expect(filterAccountsByQuery(list, '主')).toHaveLength(1)
    expect(filterAccountsByQuery(list, '额度')).toHaveLength(1)
    expect(filterAccountsByQuery(list, '')).toHaveLength(2)
  })

  it("sorts account names with natural numeric order", () => {
    const names = ["11", "1", "9", "账号11", "账号9", "账号1"]
    names.sort(compareAccountNames)
    expect(names).toEqual(["1", "9", "11", "账号1", "账号9", "账号11"])
  })
})
