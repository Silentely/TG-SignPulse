import { describe, it, expect } from 'vitest'
import { BUILT_IN_TEMPLATES, buildPayloadFromTemplate } from '../lib/task-templates'

describe('task-templates', () => {
  it('has at least 2 templates', () => {
    expect(BUILT_IN_TEMPLATES.length).toBeGreaterThanOrEqual(2)
  })

  it('builds send_text fixed task', () => {
    const p = buildPayloadFromTemplate('simple_text', {
      account_name: 'a1',
      chat_id: 123,
    })
    expect(p.execution_mode).toBe('fixed')
    expect(p.chats[0].actions[0].action).toBe(1)
    expect(p.account_name).toBe('a1')
    expect(p.chats[0].chat_id).toBe(123)
  })

  it('throws on unknown template', () => {
    expect(() =>
      buildPayloadFromTemplate('nope', { account_name: 'a' }),
    ).toThrow(/unknown template/)
  })
})
