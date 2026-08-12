/**
 * datetime 格式化：24 小时制、空值兜底、解析失败回退原值、时区可切换。
 */
import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatShortDateTime,
  formatTimeOnly,
  getPanelTimezone,
  setPanelTimezone,
} from '../lib/datetime'

describe('datetime 格式化', () => {
  const iso = '2026-07-01T10:05:09Z'

  afterEach(() => {
    // 恢复默认时区，避免用例间互相污染
    setPanelTimezone('Asia/Hong_Kong')
  })

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

  it('formatShortDateTime 输出 MM/DD HH:MM，可选秒（默认 Asia/Hong_Kong 时区）', () => {
    // 与 formatTimeOnly/formatDateTime 一致：按默认展示时区（UTC+8）输出
    expect(formatShortDateTime(iso)).toBe('07/01 18:05')
    expect(formatShortDateTime(iso, true)).toBe('07/01 18:05:09')
    expect(formatShortDateTime('')).toBe('-')
    expect(formatShortDateTime('bad')).toBe('bad')
  })

  it('setPanelTimezone 切换后全部格式化函数跟随新时区', () => {
    setPanelTimezone('UTC')
    expect(getPanelTimezone()).toBe('UTC')
    expect(formatTimeOnly(iso)).toBe('10:05:09') // UTC 原值
    expect(formatShortDateTime(iso)).toBe('07/01 10:05')
  })

  it('setPanelTimezone 忽略空值，保留当前时区', () => {
    setPanelTimezone('UTC')
    setPanelTimezone('')
    setPanelTimezone(null)
    setPanelTimezone(undefined)
    expect(getPanelTimezone()).toBe('UTC')
  })
})
