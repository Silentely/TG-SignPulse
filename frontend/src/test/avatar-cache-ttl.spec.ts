/**
 * 头像本地缓存编解码测试：
 * 新格式 {v, ts} 带 TTL；旧版纯 dataURL 兼容；损坏/过期值返回 null。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  buildAvatarCache,
  parseAvatarCache,
} from '../composables/useTaskListRuntime'

const DATA_URL = 'data:image/png;base64,AAAA'

describe('avatar cache helpers', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-19T00:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('buildAvatarCache 写入 {v, ts} 结构并可解析回 dataURL', () => {
    const raw = buildAvatarCache(DATA_URL)
    const parsed = JSON.parse(raw) as { v: string; ts: number }
    expect(parsed.v).toBe(DATA_URL)
    expect(parsed.ts).toBeGreaterThan(0)
    expect(parseAvatarCache(raw)).toBe(DATA_URL)
  })

  it('未过期的新格式缓存返回 dataURL', () => {
    const raw = buildAvatarCache(DATA_URL)
    vi.advanceTimersByTime(6 * 24 * 3600 * 1000) // 6 天，未过 7 天 TTL
    expect(parseAvatarCache(raw)).toBe(DATA_URL)
  })

  it('超过 TTL 的缓存返回 null（触发重新拉取）', () => {
    const raw = buildAvatarCache(DATA_URL)
    vi.advanceTimersByTime(8 * 24 * 3600 * 1000) // 8 天，超过 7 天 TTL
    expect(parseAvatarCache(raw)).toBeNull()
  })

  it('兼容旧版纯 dataURL 字符串缓存', () => {
    expect(parseAvatarCache(DATA_URL)).toBe(DATA_URL)
  })

  it('空值/占位/损坏值返回 null', () => {
    expect(parseAvatarCache(null)).toBeNull()
    expect(parseAvatarCache('')).toBeNull()
    expect(parseAvatarCache('__no_avatar__')).toBeNull()
    expect(parseAvatarCache('not-json')).toBeNull()
    expect(parseAvatarCache('{"v":123}')).toBeNull()
    expect(parseAvatarCache('{"v":"http://x"}')).toBeNull() // 非 data: 协议
  })
})
