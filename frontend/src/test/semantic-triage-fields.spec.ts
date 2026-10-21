import { describe, expect, it } from 'vitest'
import { parseActions, buildActions } from '../lib/task-form-utils'

describe('semantic_triage form utils roundtrip', () => {
  it('parses semantic_triage correctly from backend raw action', () => {
    const rawActions = [
      {
        action: 1,
        text: '签到',
        semantic_triage: {
          mode: 'assist',
          min_probability: 0.97,
          min_margin: 0.25,
        },
      },
    ]

    const parsed = parseActions(rawActions as any)
    expect(parsed.length).toBe(1)
    expect(parsed[0].semantic_triage).toBeDefined()
    expect(parsed[0].semantic_triage?.mode).toBe('assist')
    expect(parsed[0].semantic_triage?.min_probability).toBe(0.97)

    const rebuilt = buildActions(parsed)
    expect(rebuilt.length).toBe(1)
    expect(rebuilt[0].semantic_triage).toBeDefined()
    expect(rebuilt[0].semantic_triage?.mode).toBe('assist')
    expect(rebuilt[0].semantic_triage?.min_probability).toBe(0.97)
  })
})
