import { describe, expect, it, beforeEach } from 'vitest'
import {
  buildListenAction,
  buildTaskFormPayload,
} from '../lib/task-form-payload'
import { resetActionIdCounter } from '../lib/task-form-utils'

beforeEach(() => {
  resetActionIdCounter()
})

describe('buildListenAction', () => {
  it('builds keyword monitor action with continue_actions', () => {
    const la = buildListenAction(
      {
        listenerKeywords: 'hello\nworld\n',
        listenerMatchMode: 'contains',
        listenerPushChannel: 'continue',
        listenerForwardChatId: '',
        listenerForwardThreadId: '',
        listenerBarkUrl: '',
        listenerCustomUrl: '',
        listenerServerChanKey: '',
        listenerIgnoreSelf: true,
        listenerTimeWindowEnabled: true,
        listenerActiveTimeStart: '9:00',
        listenerActiveTimeEnd: '22:30:00',
      },
      [{ action: 1, text: 'hi' }],
    )
    expect(la.action).toBe(8)
    expect(la.keywords).toEqual(['hello', 'world'])
    expect(la.active_time_start).toBe('09:00')
    expect(la.active_time_end).toBe('22:30')
    expect(la.continue_actions).toHaveLength(1)
  })
})

describe('buildTaskFormPayload', () => {
  it('builds range schedule and multi-chat payload', () => {
    const payload = buildTaskFormPayload({
      taskName: 'daily',
      selectedAccounts: ['acc1', 'acc2'],
      allAccountsMode: false,
      scheduleMode: 'scheduled',
      timeRange: '08:00-19:00',
      retryCount: 2,
      targetChats: [
        {
          chatId: -100,
          chatName: 'g1',
          messageThreadId: '12',
          senderFilter: '',
          sourceAccount: 'acc1',
        },
        {
          chatId: 0,
          chatName: 'skip',
          messageThreadId: '',
          senderFilter: '',
          sourceAccount: '',
        },
      ],
      fallbackChatId: 0,
      fallbackChatName: '',
      fallbackThreadId: '',
      fallbackSenderFilter: '',
      fallbackSourceAccount: '',
      actions: [{ id: 1, type: 'send_text', value: '签到', aiPrompt: '' }],
      listenerKeywords: '',
      listenerMatchMode: 'contains',
      listenerPushChannel: 'continue',
      listenerForwardChatId: '',
      listenerForwardThreadId: '',
      listenerBarkUrl: '',
      listenerCustomUrl: '',
      listenerServerChanKey: '',
      listenerIgnoreSelf: true,
      listenerTimeWindowEnabled: false,
      listenerActiveTimeStart: '09:00',
      listenerActiveTimeEnd: '22:00',
    })
    expect(payload.name).toBe('daily')
    expect(payload.execution_mode).toBe('range')
    expect(payload.range_start).toBe('08:00')
    expect(payload.range_end).toBe('19:00')
    expect(payload.account_names).toEqual(['acc1', 'acc2'])
    expect(payload.chats?.length).toBe(1)
    expect(payload.chats?.[0]?.chat_id).toBe(-100)
    expect(payload.chats?.[0]?.message_thread_id).toBe(12)
  })

  it('uses wildcard account_names in allAccountsMode', () => {
    const payload = buildTaskFormPayload({
      taskName: 'all',
      selectedAccounts: ['a', 'b'],
      allAccountsMode: true,
      scheduleMode: 'listen',
      timeRange: '08:00',
      retryCount: 1,
      targetChats: [],
      fallbackChatId: 1,
      fallbackChatName: 'c',
      fallbackThreadId: '',
      fallbackSenderFilter: '',
      fallbackSourceAccount: 'a',
      actions: [],
      listenerKeywords: 'kw',
      listenerMatchMode: 'exact',
      listenerPushChannel: 'bark',
      listenerForwardChatId: '',
      listenerForwardThreadId: '',
      listenerBarkUrl: 'https://bark.example/x',
      listenerCustomUrl: '',
      listenerServerChanKey: '',
      listenerIgnoreSelf: false,
      listenerTimeWindowEnabled: false,
      listenerActiveTimeStart: '09:00',
      listenerActiveTimeEnd: '22:00',
    })
    expect(payload.account_names).toEqual(['*'])
    expect(payload.execution_mode).toBe('listen')
    expect(payload.chats?.[0]?.actions?.[0]?.action).toBe(8)
    expect(payload.chats?.[0]?.actions?.[0]?.bark_url).toBe('https://bark.example/x')
  })
})
