import { describe, expect, it } from 'vitest'
import {
  filterTasksByModeAndQuery,
  hasActiveListFilters,
  type TaskListFilterItem,
} from '../lib/task-list-filter'

const sample: TaskListFilterItem[] = [
  {
    name: 'daily_a',
    targetStr: 'chat1',
    scheduleMode: '08:00',
    lastRunStr: '成功',
    isListenMode: false,
    tags: ['checkin', 'daily'],
  },
  {
    name: 'listen_b',
    targetStr: 'group',
    scheduleMode: '监听',
    lastRunStr: '持续运行',
    isListenMode: true,
  },
  {
    name: 'other',
    targetStr: 'xyz',
    scheduleMode: '09:00',
    lastRunStr: '失败',
    isListenMode: false,
  },
]

describe('filterTasksByModeAndQuery', () => {
  it('filters by listen mode', () => {
    const r = filterTasksByModeAndQuery(sample, 'listen', '')
    expect(r).toHaveLength(1)
    expect(r[0].name).toBe('listen_b')
  })

  it('filters by scheduled mode', () => {
    const r = filterTasksByModeAndQuery(sample, 'scheduled', '')
    expect(r.every((t) => !t.isListenMode)).toBe(true)
    expect(r).toHaveLength(2)
  })

  it('filters by search query across fields', () => {
    expect(filterTasksByModeAndQuery(sample, 'all', 'daily')).toHaveLength(1)
    expect(filterTasksByModeAndQuery(sample, 'all', 'group')).toHaveLength(1)
    expect(filterTasksByModeAndQuery(sample, 'all', '失败')).toHaveLength(1)
  })

  it('combines mode and search', () => {
    const r = filterTasksByModeAndQuery(sample, 'scheduled', 'other')
    expect(r).toHaveLength(1)
    expect(r[0].name).toBe('other')
  })

  it('filters by tag', () => {
    const r = filterTasksByModeAndQuery(sample, 'all', '', 'checkin')
    expect(r).toHaveLength(1)
    expect(r[0].name).toBe('daily_a')

    const empty = filterTasksByModeAndQuery(sample, 'all', '', 'nonexistent')
    expect(empty).toHaveLength(0)
  })

  it('searches query in tags', () => {
    const r = filterTasksByModeAndQuery(sample, 'all', 'checkin')
    expect(r).toHaveLength(1)
    expect(r[0].name).toBe('daily_a')
  })
})

describe('hasActiveListFilters', () => {
  it('detects search, mode and account filter', () => {
    expect(hasActiveListFilters('', 'all', '')).toBe(false)
    expect(hasActiveListFilters('x', 'all', '')).toBe(true)
    expect(hasActiveListFilters('', 'listen', '')).toBe(true)
    expect(hasActiveListFilters('', 'all', 'acc1')).toBe(true)
    expect(hasActiveListFilters('', 'all', '', 'daily')).toBe(true)
  })
})
