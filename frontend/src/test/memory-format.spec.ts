import { describe, expect, it } from 'vitest'
import { formatMemoryRssFromStats } from '../lib/memory-format'

describe('formatMemoryRssFromStats', () => {
  it('优先使用后端 current_rss_mb', () => {
    expect(
      formatMemoryRssFromStats({ current_rss_mb: 128.456 }, '未知'),
    ).toBe('128.5 MB')
  })

  it('兼容 rss_mb / rss_bytes 别名', () => {
    expect(formatMemoryRssFromStats({ rss_mb: 64 }, '未知')).toBe('64.0 MB')
    expect(
      formatMemoryRssFromStats({ rss_bytes: 32 * 1024 * 1024 }, '未知'),
    ).toBe('32.0 MB')
  })

  it('无有效字段时返回未知文案', () => {
    expect(formatMemoryRssFromStats({}, '未知')).toBe('未知')
    expect(formatMemoryRssFromStats(null, 'unknown')).toBe('unknown')
    expect(formatMemoryRssFromStats({ current_rss_mb: 'n/a' }, '未知')).toBe(
      '未知',
    )
  })
})
