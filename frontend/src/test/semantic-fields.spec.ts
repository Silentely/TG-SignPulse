import { describe, expect, it } from 'vitest'
import { parseActions, buildActions } from '../lib/task-form-utils'

describe('Semantic action policies roundtrip', () => {
  it('preserves semantic_result policy across parse and build', () => {
    const rawActions = [
      {
        action: 1,
        text: '/checkin',
        wait_for_reply: true,
        semantic_result: {
          mode: 'observe',
          goal: '签到奖励到账',
          min_probability: 0.97,
          min_margin: 0.25,
        },
      },
    ]

    const parsed = parseActions(rawActions as any)
    const rebuilt = buildActions(parsed as any)

    expect(rebuilt[0]).toHaveProperty('semantic_result')
    expect((rebuilt[0] as any).semantic_result.goal).toBe('签到奖励到账')
    expect((rebuilt[0] as any).semantic_result.mode).toBe('observe')
  })
})
