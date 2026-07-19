import { describe, expect, it } from 'vitest'
import {
  aggregateFailureCategories,
  badgeTone,
  formatPhaseDetail,
  isRunInProgress,
  phaseLabel,
  stateLabel,
} from '../lib/run-status'

const t = (key: string) => {
  const map: Record<string, string> = {
    'runStatus.phase.cooldown': '账号冷却',
    'runStatus.phase.running': '执行中',
    'runStatus.state.timeout': '超时',
    'runStatus.state.running': '进行中',
  }
  return map[key] || key
}

describe('run-status helpers', () => {
  it('isRunInProgress', () => {
    expect(isRunInProgress({ state: 'running' })).toBe(true)
    expect(isRunInProgress({ state: 'finished' })).toBe(false)
    expect(isRunInProgress(null)).toBe(false)
  })

  it('phase and state labels', () => {
    expect(phaseLabel('cooldown', t)).toBe('账号冷却')
    expect(phaseLabel('unknown_phase', t)).toBe('unknown_phase')
    expect(stateLabel('timeout', t)).toBe('超时')
  })

  it('formatPhaseDetail prefers phase_detail', () => {
    expect(
      formatPhaseDetail({ phase: 'cooldown', phase_detail: '等待账号冷却 12 秒' }, t),
    ).toBe('等待账号冷却 12 秒')
    expect(formatPhaseDetail({ phase: 'running', phase_detail: '' }, t)).toBe('执行中')
  })

  it('badgeTone by state/phase', () => {
    expect(badgeTone({ state: 'running', phase: 'cooldown' })).toBe('amber')
    expect(badgeTone({ state: 'running', phase: 'running' })).toBe('sky')
    expect(badgeTone({ state: 'timeout', success: false })).toBe('rose')
    expect(badgeTone({ state: 'finished', success: true })).toBe('emerald')
  })

  it('aggregateFailureCategories', () => {
    const items = aggregateFailureCategories([
      { success: true, failure_category: 'none' },
      { success: false, failure_category: 'timeout' },
      { success: false, failure_category: 'timeout' },
      { success: false, failure_category: 'session_invalid' },
      { success: false, failure_category: null },
    ])
    expect(items[0]).toEqual({ category: 'timeout', count: 2 })
    expect(items.find((x) => x.category === 'session_invalid')?.count).toBe(1)
    expect(items.find((x) => x.category === 'unknown')?.count).toBe(1)
  })
})
