/**
 * TaskForm payload 纯函数：从 UI 草稿构造 Create/Update 请求体。
 * 与 Vue 组件解耦，便于单测与复用。
 */
import type { CreateSignTaskRequest } from './api'
import type { BuiltAction, RawTaskAction, TaskActionItem } from './types'
import { buildActions } from './task-form-utils'

export type TargetChatDraftLike = {
  chatId: number
  chatName: string
  messageThreadId: string
  senderFilter: string
  sourceAccount: string
}

export type TaskFormPayloadInput = {
  taskName: string
  selectedAccounts: string[]
  allAccountsMode: boolean
  scheduleMode: 'scheduled' | 'listen'
  timeRange: string
  retryCount: number
  targetChats: TargetChatDraftLike[]
  /** 无有效目标时的回退 chat */
  fallbackChatId: number
  fallbackChatName: string
  fallbackThreadId: string
  fallbackSenderFilter: string
  fallbackSourceAccount: string
  actions: TaskActionItem[]
  listenerKeywords: string
  listenerMatchMode: string
  listenerPushChannel: string
  listenerForwardChatId: string
  listenerForwardThreadId: string
  listenerBarkUrl: string
  listenerCustomUrl: string
  listenerServerChanKey: string
  listenerIgnoreSelf: boolean
  listenerTimeWindowEnabled: boolean
  listenerActiveTimeStart: string
  listenerActiveTimeEnd: string
}

function normalizeTimeHm(v: string): string {
  const m = v.trim().match(/^(\d{1,2}):(\d{2})/)
  return m ? `${m[1].padStart(2, '0')}:${m[2]}` : v.trim()
}

/** 组装监听动作（action=8）及可选 continue_actions */
export function buildListenAction(
  input: Pick<
    TaskFormPayloadInput,
    | 'listenerKeywords'
    | 'listenerMatchMode'
    | 'listenerPushChannel'
    | 'listenerForwardChatId'
    | 'listenerForwardThreadId'
    | 'listenerBarkUrl'
    | 'listenerCustomUrl'
    | 'listenerServerChanKey'
    | 'listenerIgnoreSelf'
    | 'listenerTimeWindowEnabled'
    | 'listenerActiveTimeStart'
    | 'listenerActiveTimeEnd'
  >,
  continueActions: BuiltAction[],
): BuiltAction {
  const kw = input.listenerKeywords
    .split('\n')
    .map((k: string) => k.trim())
    .filter(Boolean)
  const la: BuiltAction = {
    action: 8,
    keywords: kw,
    match_mode: input.listenerMatchMode,
    push_channel: input.listenerPushChannel,
    ignore_self: input.listenerIgnoreSelf,
  }
  if (input.listenerTimeWindowEnabled) {
    const start = normalizeTimeHm(input.listenerActiveTimeStart)
    const end = normalizeTimeHm(input.listenerActiveTimeEnd)
    if (start && end) {
      la.active_time_start = start
      la.active_time_end = end
    }
  }
  if (input.listenerPushChannel === 'forward') {
    if (input.listenerForwardChatId) la.forward_chat_id = input.listenerForwardChatId
    if (input.listenerForwardThreadId) {
      la.forward_message_thread_id = input.listenerForwardThreadId
    }
  }
  if (input.listenerPushChannel === 'bark' && input.listenerBarkUrl) {
    la.bark_url = input.listenerBarkUrl
  }
  if (input.listenerPushChannel === 'custom' && input.listenerCustomUrl) {
    la.custom_url = input.listenerCustomUrl
  }
  if (input.listenerPushChannel === 'server_chan' && input.listenerServerChanKey) {
    la.server_chan_send_key = input.listenerServerChanKey
  }
  if (input.listenerPushChannel === 'continue' && continueActions.length > 0) {
    la.continue_actions = continueActions
  }
  return la
}

export function buildTaskFormPayload(
  input: TaskFormPayloadInput,
): CreateSignTaskRequest {
  let em: 'fixed' | 'range' | 'listen' = 'fixed'
  let sa = '08:00'
  let rs = ''
  let re = ''
  if (input.scheduleMode === 'listen') {
    em = 'listen'
  } else {
    const p = input.timeRange.split('-')
    if (p.length === 2) {
      em = 'range'
      rs = p[0].trim()
      re = p[1].trim()
      sa = rs
    } else {
      sa = input.timeRange.trim() || '08:00'
    }
  }

  const ba = buildActions(input.actions)
  let ca: BuiltAction[] = ba
  if (input.scheduleMode === 'listen') {
    ca = [buildListenAction(input, ba)]
  }

  const seenChatIds = new Set<number>()
  const chats = input.targetChats
    .filter((c) => {
      const id = Number(c.chatId)
      if (!Number.isFinite(id) || id === 0) return false
      if (seenChatIds.has(id)) return false
      seenChatIds.add(id)
      return true
    })
    .map((c) => ({
      chat_id: c.chatId,
      name: c.chatName,
      actions: ca as RawTaskAction[],
      action_interval: 1,
      message_thread_id: c.messageThreadId ? Number(c.messageThreadId) : undefined,
      sender_filter: c.senderFilter.trim() || undefined,
      source_account: c.sourceAccount || undefined,
    }))

  const safeChats = chats.length
    ? chats
    : [
        {
          chat_id: input.fallbackChatId || 0,
          name: input.fallbackChatName || '',
          actions: ca as RawTaskAction[],
          action_interval: 1,
          message_thread_id: input.fallbackThreadId
            ? Number(input.fallbackThreadId)
            : undefined,
          sender_filter: input.fallbackSenderFilter.trim() || undefined,
          source_account: input.fallbackSourceAccount || undefined,
        },
      ]

  const primaryName = safeChats[0]?.name || input.fallbackChatName
  return {
    name: input.taskName || primaryName || `task_${Date.now()}`,
    account_name: input.selectedAccounts[0] || '',
    account_names: input.allAccountsMode ? ['*'] : input.selectedAccounts,
    sign_at: sa,
    execution_mode: em,
    range_start: rs,
    range_end: re,
    random_seconds: 0,
    retry_count: input.retryCount,
    chats: safeChats,
  }
}
