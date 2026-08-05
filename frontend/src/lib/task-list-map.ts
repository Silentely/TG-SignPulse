/**
 * 签到列表：SignTask API → TaskUiItem 展示映射（纯逻辑）。
 */
import { formatShortDateTime } from './datetime'
import type { SignTask } from './api'
import type { TaskUiItem } from './types'

export type TaskListMapLabels = {
  noTarget: string
  listenMode: string
  notExecuted: string
  continuousRunning: string
  paused: string
  success: string
  failed: string
}

export type ModeIconKind = 'clock' | 'radio' | 'shuffle'

export type MappedTaskListFields = {
  id: string
  name: string
  scheduleMode: string
  targetStr: string
  targetCount: number
  hitCount: number
  lastRunStr: string
  lastRunSuccess: boolean | null
  modeIconKind: ModeIconKind
  isListenMode: boolean
  enabled: boolean
  chatAvatarUrl: string
  chatName: string
  raw: SignTask
}

export type TaskAccountSource =
  | SignTask
  | TaskUiItem
  | { account_name?: string; account_names?: string[] }

function unwrapTaskSource(
  task: TaskAccountSource,
): SignTask | { account_name?: string; account_names?: string[] } {
  return 'raw' in task ? task.raw : task
}

export function resolveTaskAccountName(task: TaskAccountSource): string {
  const raw = unwrapTaskSource(task)
  const name = raw.account_name || ''
  if (name && name !== '*') return name
  const names = raw.account_names || []
  for (const n of names) {
    if (n && n !== '*') return n
  }
  return ''
}

/** 任务关联的具体账号名（去重、跳过通配符，不展开）。 */
export function resolveTaskAccountNames(task: TaskAccountSource): string[] {
  const raw = unwrapTaskSource(task)
  const names = raw.account_names || []
  const seen = new Set<string>()
  const result: string[] = []
  for (const n of [...names, raw.account_name || '']) {
    if (n && n !== '*' && !seen.has(n)) {
      seen.add(n)
      result.push(n)
    }
  }
  return result
}

export function resolveTaskRealAccounts(
  task: TaskAccountSource,
  allAccounts: string[],
): string[] {
  const raw = unwrapTaskSource(task)
  const names = raw.account_names || []
  if (names.includes('*')) {
    return allAccounts.length > 0 ? allAccounts : []
  }
  return names.filter((n: string) => n && n !== '*')
}

/** API 任务 → 列表行字段（modeIcon 由调用方按 kind 绑定组件） */
export function mapSignTaskToListFields(
  task: SignTask,
  labels: TaskListMapLabels,
): MappedTaskListFields {
  const chats = task.chats || []
  const firstChat = chats.length > 0 ? chats[0] : null
  const targetCount = chats.length
  const primaryLabel = firstChat
    ? firstChat.name ||
      `${firstChat.chat_id}${firstChat.message_thread_id ? '|' + firstChat.message_thread_id : ''}`
    : labels.noTarget
  const targetStr = primaryLabel

  let scheduleMode = ''
  let modeIconKind: ModeIconKind = 'clock'
  if (task.execution_mode === 'listen') {
    scheduleMode = labels.listenMode
    modeIconKind = 'radio'
  } else if (task.execution_mode === 'range') {
    scheduleMode = `${task.range_start || '00:00'}-${task.range_end || '23:59'}`
    modeIconKind = 'shuffle'
  } else {
    scheduleMode = task.sign_at || '00:00'
    modeIconKind = 'clock'
  }

  let lastRunStr = labels.notExecuted
  let lastRunSuccess: boolean | null = null
  if (task.execution_mode === 'listen' && !task.last_run) {
    lastRunStr = task.enabled !== false ? labels.continuousRunning : labels.paused
  }
  if (task.last_run) {
    lastRunSuccess = task.last_run.success
    // 统一面板时区（Asia/Hong_Kong），与日志弹窗/仪表盘展示一致
    lastRunStr = `${task.last_run.success ? labels.success : labels.failed}-${formatShortDateTime(task.last_run.time, true)}`
  }

  return {
    id: task.name,
    name: task.name,
    scheduleMode,
    targetStr,
    targetCount,
    hitCount: 0,
    lastRunStr,
    lastRunSuccess,
    modeIconKind,
    isListenMode: task.execution_mode === 'listen',
    enabled: task.enabled !== false,
    chatAvatarUrl: '',
    chatName: firstChat ? firstChat.name || `Chat ${firstChat.chat_id}` : '',
    raw: task,
  }
}

/** 将 modeIconKind 绑定为具体图标组件后得到 TaskUiItem */
export function withModeIcon(
  fields: MappedTaskListFields,
  modeIcon: TaskUiItem['modeIcon'],
): TaskUiItem {
  const { modeIconKind: _kind, ...rest } = fields
  return { ...rest, modeIcon }
}
