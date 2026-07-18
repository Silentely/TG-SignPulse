import { describe, it, expect } from 'vitest'
import {
  BUILT_IN_TEMPLATES,
  buildPayloadFromTemplate,
  buildSignTaskFromTemplate,
  getTemplateById,
} from '../lib/task-templates'

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

  it('getTemplateById returns known template', () => {
    expect(getTemplateById('click_button')?.execution_mode).toBe('fixed')
    expect(getTemplateById('missing')).toBeUndefined()
  })

  it('buildSignTaskFromTemplate prefills actions for TaskForm', () => {
    const task = buildSignTaskFromTemplate('click_button', {
      account_name: 'acc1',
      task_name: 'tpl_demo',
    })
    expect(task.name).toBe('tpl_demo')
    expect(task.account_name).toBe('acc1')
    expect(task.chats[0].actions?.length).toBe(2)
    expect(task.chats[0].actions?.[0].action).toBe(1)
    expect(task.chats[0].actions?.[1].action).toBe(3)
    // 允许 chat_id=0，由用户在表单中选择会话
    expect(task.chats[0].chat_id).toBe(0)
  })
})
