/**
 * TaskForm payload 纯函数：从 UI 草稿构造 Create/Update 请求体。
 * 与 Vue 组件解耦，便于单测与复用。
 */
import type { CreateSignTaskRequest, SignTask, SignTaskChat, UpdateSignTaskRequest } from './api'
import type { BuiltAction, RawTaskAction, TaskActionItem } from './types'
import { buildActions, actionsToFlowSteps } from './task-form-utils'

/** Only form-owned metadata is eligible for this patch. Flow and runtime defaults
 * must never leak into a metadata save. Compare against the initialized draft,
 * since older configs may omit defaults that the form displays. */
const metadataFields = [
  'account_names', 'sign_at', 'execution_mode', 'range_start', 'range_end',
  'retry_count', 'tags', 'adaptive_schedule_enabled', 'adaptive_schedule_patterns',
  'adaptive_schedule_padding_seconds', 'next_task_on_success',
  'next_task_delay_seconds', 'execution_engine',
] as const

export function buildTaskMetadataPatch(
  original: SignTask,
  draft: Partial<CreateSignTaskRequest>,
  initialDraft: Partial<CreateSignTaskRequest> = original,
): UpdateSignTaskRequest {
  const patch: UpdateSignTaskRequest = { revision: original.revision, field_mask: [] }
  for (const field of metadataFields) {
    if (draft[field] !== undefined && JSON.stringify(draft[field]) !== JSON.stringify(initialDraft[field])) {
      Object.assign(patch, { [field]: draft[field] })
      patch.field_mask!.push(field)
    }
  }
  return patch
}

export function taskTargetKey(chat: Pick<SignTaskChat, 'chat_id' | 'message_thread_id'>): string {
  return `${chat.chat_id}:${chat.message_thread_id ?? ''}`
}

export function buildTargetFlowPatch(
  original: SignTask,
  targetKey: string,
  flow: Partial<Pick<SignTaskChat, 'actions' | 'steps' | 'flow_graph' | 'initial_step_id'>>,
): UpdateSignTaskRequest | null {
  if (!original.chats.some(chat => taskTargetKey(chat) === targetKey)) return null
  return {
    revision: original.revision,
    field_mask: ['chats'],
    chats: original.chats.map(chat => {
      if (taskTargetKey(chat) !== targetKey) return JSON.parse(JSON.stringify(chat))
      const updated = { ...chat }
      for (const key of ['actions', 'steps', 'flow_graph', 'initial_step_id'] as const) delete updated[key]
      return { ...updated, ...flow }
    }),
  }
}

export type TargetChatDraftLike = {
  chatId: number
  chatName: string
  messageThreadId: string
  senderFilter: string
  sourceAccount: string
  steps?: any[]
  flow_graph?: Record<string, any>
  initial_step_id?: string
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
  tags?: string[]
  jitterSeconds?: number | string
  adaptiveScheduleEnabled?: boolean
  adaptiveSchedulePaddingSeconds?: number
  adaptiveSchedulePatterns?: string[]
  nextTaskOnSuccess?: string
  nextTaskDelaySeconds?: number
  executionEngine?: string | null
  flowMode?: "basic" | "advanced"
  flowSteps?: any[]
  flowGraph?: Record<string, any>
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

  const isAdvanced = input.flowMode === "advanced"
  const hasWaitForReply = !isAdvanced && ca.some((a) => (a as any).wait_for_reply)
  const defaultEngine = (isAdvanced || hasWaitForReply) ? "v4" : undefined
  const effectiveEngine = input.executionEngine?.trim() || defaultEngine

  const seenChatTargets = new Set<string>()
  const chats = input.targetChats
    .filter((c) => {
      const id = Number(c.chatId)
      if (!Number.isFinite(id) || id === 0) return false
      const threadId = c.messageThreadId ? Number(c.messageThreadId) : ""
      const targetKey = `${id}:${threadId}`
      if (seenChatTargets.has(targetKey)) return false
      seenChatTargets.add(targetKey)
      return true
    })
    .map((c) => {
      const chatSteps = c.steps || (isAdvanced ? input.flowSteps : undefined)
      const chatGraph = c.flow_graph || (isAdvanced ? input.flowGraph : undefined)

      const chatObj: any = {
        chat_id: c.chatId,
        name: c.chatName,
        action_interval: 1,
        message_thread_id: c.messageThreadId ? Number(c.messageThreadId) : undefined,
        sender_filter: c.senderFilter ? c.senderFilter.trim() || undefined : undefined,
        source_account: c.sourceAccount || undefined,
        execution_engine: input.executionEngine?.trim() || (isAdvanced || hasWaitForReply ? "v4" : undefined),
      }

      if (isAdvanced && (chatGraph || chatSteps)) {
        if (chatGraph) {
          chatObj.flow_graph = chatGraph
        } else if (chatSteps) {
          chatObj.steps = chatSteps
          if (c.initial_step_id) {
            chatObj.initial_step_id = c.initial_step_id
          }
        }
      } else if (hasWaitForReply) {
        chatObj.steps = actionsToFlowSteps(ca)
      } else {
        chatObj.actions = ca as RawTaskAction[]
      }
      return chatObj
    })

  const safeChats = chats.length
    ? chats
    : [
        (() => {
          const chatSteps = isAdvanced ? input.flowSteps : undefined
          const chatGraph = isAdvanced ? input.flowGraph : undefined
          const chatObj: any = {
            chat_id: input.fallbackChatId || 0,
            name: input.fallbackChatName || "",
            action_interval: 1,
            message_thread_id: input.fallbackThreadId
              ? Number(input.fallbackThreadId)
              : undefined,
            sender_filter: input.fallbackSenderFilter ? input.fallbackSenderFilter.trim() || undefined : undefined,
            source_account: input.fallbackSourceAccount || undefined,
            execution_engine: input.executionEngine?.trim() || (isAdvanced || hasWaitForReply ? "v4" : undefined),
          }
          if (isAdvanced && (chatGraph || chatSteps)) {
            if (chatGraph) {
              chatObj.flow_graph = chatGraph
            } else if (chatSteps) {
              chatObj.steps = chatSteps
            }
          } else if (hasWaitForReply) {
            chatObj.steps = actionsToFlowSteps(ca)
          } else {
            chatObj.actions = ca as RawTaskAction[]
          }
          return chatObj
        })(),
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
    jitter_seconds: input.jitterSeconds !== undefined && String(input.jitterSeconds).trim() !== '' ? Number(input.jitterSeconds) : undefined,
    retry_count: input.retryCount,
    tags: input.tags || [],
    adaptive_schedule_enabled: Boolean(input.adaptiveScheduleEnabled),
    adaptive_schedule_padding_seconds: input.adaptiveSchedulePaddingSeconds !== undefined ? Number(input.adaptiveSchedulePaddingSeconds) : 30,
    adaptive_schedule_patterns: input.adaptiveSchedulePatterns || [],
    next_task_on_success: input.nextTaskOnSuccess?.trim() ? input.nextTaskOnSuccess.trim() : undefined,
    next_task_delay_seconds: input.nextTaskDelaySeconds !== undefined && String(input.nextTaskDelaySeconds).trim() !== '' ? Number(input.nextTaskDelaySeconds) : undefined,
    execution_engine: effectiveEngine,
    chats: safeChats,
  }
}
