/**
 * datetime 格式化：24 小时制、空值兜底、解析失败回退原值。
 */
import { describe, expect, it } from 'vitest'
import { formatDateTime, formatShortDateTime, formatTimeOnly } from '../lib/datetime'

describe('datetime 格式化', () => {
  const iso = '2026-07-01T10:05:09Z'

  it('formatTimeOnly 仅输出时间且为 24 小时制', () => {
    expect(formatTimeOnly(iso)).toBe('18:05:09') // UTC+8
    expect(formatTimeOnly('')).toBe('')
    expect(formatTimeOnly(null)).toBe('')
    expect(formatTimeOnly('not-a-date')).toBe('not-a-date')
  })

  it('formatDateTime 输出完整日期时间，空值回落 fallback', () => {
    expect(formatDateTime(iso)).toContain('2026')
    expect(formatDateTime('')).toBe('-')
    expect(formatDateTime(null, undefined, '--')).toBe('--')
    expect(formatDateTime('garbage')).toBe('garbage')
  })

  it('formatShortDateTime 输出 MM/DD HH:MM，可选秒', () => {
    // 显式选项不受语言区域影响，使用固定时区断言
    const local = new Date(iso)
    const mo = String(local.getMonth() + 1).padStart(2, '0')
    const da = String(local.getDate()).padStart(2, '0')
    const ho = String(local.getHours()).padStart(2, '0')
    const mi = String(local.getMinutes()).padStart(2, '0')
    const se = String(local.getSeconds()).padStart(2, '0')
    expect(formatShortDateTime(iso)).toBe(`${mo}/${da} ${ho}:${mi}`)
    expect(formatShortDateTime(iso, true)).toBe(`${mo}/${da} ${ho}:${mi}:${se}`)
    expect(formatShortDateTime('')).toBe('-')
    expect(formatShortDateTime('bad')).toBe('bad')
  })
})
