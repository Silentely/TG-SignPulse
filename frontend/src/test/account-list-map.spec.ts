import { describe, it, expect } from 'vitest'
import {
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

  it('filters by name remark message', () => {
    const list = [
      { name: 'alice', remark: '主号', message: '' },
      { name: 'bob', remark: '', message: '额度不足' },
    ]
    expect(filterAccountsByQuery(list, '主')).toHaveLength(1)
    expect(filterAccountsByQuery(list, '额度')).toHaveLength(1)
    expect(filterAccountsByQuery(list, '')).toHaveLength(2)
  })
})
