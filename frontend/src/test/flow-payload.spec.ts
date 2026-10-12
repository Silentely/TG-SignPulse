import { describe, it, expect } from 'vitest'
import { buildTaskFormPayload } from '../lib/task-form-payload'

describe('flow payload serializer', () => {
  it('handles advanced flowMode and links execution_engine to v4', () => {
    const input: any = {
      accountName: 'acc_1',
      selectedAccounts: ['acc_1'],
      flowMode: 'advanced',
      scheduleMode: 'scheduled',
      timeRange: '08:00',
      targetChats: [
        {
          chatId: 1001,
          chatName: 'My Chat',
          senderFilter: '',
          messageThreadId: '',
          sourceAccount: '',
          steps: [
            { step_id: 'd1', node_type: 'delay', delay_seconds: 3, next_step_id: 'COMPLETE' }
          ]
        }
      ],
      actions: []
    }
    const payload = buildTaskFormPayload(input)
    expect(payload.chats[0].steps).toBeDefined()
    expect(payload.chats[0].actions).toBeUndefined()
    expect(payload.execution_engine).toBe('v4')
  })

  it('handles advanced flowMode with flow_graph', () => {
    const input: any = {
      accountName: 'acc_1',
      selectedAccounts: ['acc_1'],
      flowMode: 'advanced',
      scheduleMode: 'scheduled',
      timeRange: '08:00',
      targetChats: [
        {
          chatId: 1002,
          chatName: 'Graph Chat',
          senderFilter: '',
          messageThreadId: '',
          sourceAccount: '',
          flow_graph: {
            entry_node_id: 's1',
            nodes: {
              s1: { id: 's1', type: 'delay', delay_seconds: 2, next_node_id: '_TERMINAL_COMPLETE' }
            }
          }
        }
      ],
      actions: []
    }
    const payload = buildTaskFormPayload(input)
    expect(payload.chats[0].flow_graph).toBeDefined()
    expect(payload.chats[0].actions).toBeUndefined()
    expect(payload.execution_engine).toBe('v4')
  })
})
