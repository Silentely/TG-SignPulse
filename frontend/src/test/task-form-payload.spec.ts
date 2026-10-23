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

  it('preserves tags in payload', () => {
    const payload = buildTaskFormPayload({
      taskName: 'tagged_task',
      selectedAccounts: ['acc1'],
      allAccountsMode: false,
      scheduleMode: 'scheduled',
      timeRange: '08:00',
      retryCount: 3,
      tags: ['crypto', 'airdrop'],
      targetChats: [],
      fallbackChatId: 1,
      fallbackChatName: 'chat1',
      fallbackThreadId: '',
      fallbackSenderFilter: '',
      fallbackSourceAccount: 'acc1',
      actions: [],
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
    expect(payload.tags).toEqual(['crypto', 'airdrop'])
  })

  it('automatically upgrades actions to steps and execution_engine to v4 when wait_for_reply is true', () => {
    const payload = buildTaskFormPayload({
      taskName: 'sheerid_task',
      selectedAccounts: ['dahao'],
      allAccountsMode: false,
      scheduleMode: 'scheduled',
      timeRange: '08:00',
      retryCount: 3,
      targetChats: [{
        chatId: 8300459562,
        chatName: 'SheerID Verify Bot',
        messageThreadId: '',
        senderFilter: '',
        sourceAccount: 'dahao',
      }],
      fallbackChatId: 0,
      fallbackChatName: '',
      fallbackThreadId: '',
      fallbackSenderFilter: '',
      fallbackSourceAccount: '',
      actions: [
        {
          id: 1,
          type: 'send_text',
          value: '/checkin',
          aiPrompt: '',
          wait_for_reply: true,
          reply_success_patterns: ['出席率\s*成功'],
          reply_failure_patterns: ['出席率\s*失败', '签到失败', '操作失败'],
          reply_timeout_seconds: 30,
        },
      ],
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

    expect(payload.execution_engine).toBe('v4')
    expect(payload.chats?.[0]?.execution_engine).toBe('v4')
    expect(payload.chats?.[0]?.steps).toHaveLength(2)
    expect(payload.chats?.[0]?.steps?.[0]?.action_type).toBe('SEND_TEXT')
    expect(payload.chats?.[0]?.steps?.[0]?.next_step_id).toBe('step_0_wait')
    expect(payload.chats?.[0]?.steps?.[1]?.node_type).toBe('wait_event')
    expect(payload.chats?.[0]?.steps?.[1]?.success_patterns).toEqual(['出席率\s*成功'])
    expect(payload.chats?.[0]?.steps?.[1]?.failure_patterns).toEqual(['出席率\s*失败', '签到失败', '操作失败'])
    expect(payload.chats?.[0]?.steps?.[1]?.timeout_seconds).toBe(30)
    expect(payload.chats?.[0]?.steps?.[1]?.next_step_id).toBe('COMPLETE')
  })
  it('preserves target chats with same chatId but different sourceAccount', () => {
    const payload = buildTaskFormPayload({
      taskName: 'multi_acc_target',
      selectedAccounts: ['acc1', 'acc2'],
      allAccountsMode: false,
      scheduleMode: 'scheduled',
      timeRange: '08:00',
      retryCount: 1,
      targetChats: [
        {
          chatId: -100123456,
          chatName: 'Group A',
          messageThreadId: '',
          senderFilter: '',
          sourceAccount: 'acc1',
        },
        {
          chatId: -100123456,
          chatName: 'Group A',
          messageThreadId: '',
          senderFilter: '',
          sourceAccount: 'acc2',
        },
        {
          chatId: -100123456,
          chatName: 'Group A Duplicate',
          messageThreadId: '',
          senderFilter: '',
          sourceAccount: 'acc1',
        },
      ],
      fallbackChatId: 0,
      fallbackChatName: '',
      fallbackThreadId: '',
      fallbackSenderFilter: '',
      fallbackSourceAccount: '',
      actions: [{ id: 1, type: 'send_text', value: 'ping', aiPrompt: '' }],
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

    expect(payload.chats).toHaveLength(2)
    expect(payload.chats?.[0]?.source_account).toBe('acc1')
    expect(payload.chats?.[1]?.source_account).toBe('acc2')
  })
})
