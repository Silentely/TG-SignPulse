/**
 * datetime 格式化：24 小时制、空值兜底、解析失败回退原值、时区可切换。
 */
import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatLogTime,
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

  it('formatLogTime 当天仅输出时刻', () => {
    // 用当前时刻构造「今天」输入，避免测试随时间边界失败
    const now = new Date()
    const iso = now.toISOString()
    const out = formatLogTime(iso, '')
    expect(out).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('formatLogTime 跨天补 MM/DD 前缀', () => {
    // 固定 2026-07-01 与 2026-07-02，跨天输入应带日期前缀
    const d1 = formatLogTime('2026-07-01T04:00:00Z', '')
    const d2 = formatLogTime('2026-07-02T04:00:00Z', '')
    // 两个输入相差一天，后者必为跨天格式（带 MM/DD）
    expect(d2).toMatch(/^\d{2}\/\d{2} \d{2}:\d{2}:\d{2}$/)
    expect(d1 === d2).toBe(false)
  })

  it('formatLogTime 无效输入原样返回', () => {
    expect(formatLogTime('not-a-date', 'fb')).toBe('not-a-date')
    expect(formatLogTime('', 'fb')).toBe('fb')
    expect(formatLogTime(null, 'fb')).toBe('fb')
  })

  it('formatLogTime 随面板时区判定今天边界', () => {
    // 今天的 16:00 UTC：在 UTC+8 已是次日 00:00（跨天带前缀），
    // 切到 UTC 时区后仍是当天（仅时刻）
    const todayUtcIso = `${new Date().toISOString().slice(0, 10)}T16:00:00Z`
    setPanelTimezone('Asia/Hong_Kong')
    const hkOut = formatLogTime(todayUtcIso, '')
    setPanelTimezone('UTC')
    const utcOut = formatLogTime(todayUtcIso, '')
    expect(hkOut).toMatch(/^\d{2}\/\d{2} /) // 跨天：带日期前缀
    expect(utcOut).toMatch(/^\d{2}:\d{2}:\d{2}$/) // 当天：仅时刻
  })
})
