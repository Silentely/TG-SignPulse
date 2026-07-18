/**
 * 内置签到任务模板（前端草稿，保存时仍走创建 API）。
 * action 枚举与 task-form-utils / SupportAction 对齐。
 */

import type { SignTask, SignTaskChat } from './api'
import type { RawTaskAction } from './types'

export type TaskTemplate = {
  id: string
  nameKey: string
  descKey: string
  execution_mode: 'fixed' | 'range' | 'listen'
  sign_at: string
  range_start?: string
  range_end?: string
  actions: RawTaskAction[]
}

export const BUILT_IN_TEMPLATES: TaskTemplate[] = [
  {
    id: 'simple_text',
    nameKey: 'tasks.tpl.simpleText',
    descKey: 'tasks.tpl.simpleTextDesc',
    execution_mode: 'fixed',
    sign_at: '09:00',
    actions: [{ action: 1, text: '/checkin' }],
  },
  {
    id: 'click_button',
    nameKey: 'tasks.tpl.clickButton',
    descKey: 'tasks.tpl.clickButtonDesc',
    execution_mode: 'fixed',
    sign_at: '09:00',
    actions: [
      { action: 1, text: '/start' },
      { action: 3, text: '签到' },
    ],
  },
  {
    id: 'morning_range',
    nameKey: 'tasks.tpl.morningRange',
    descKey: 'tasks.tpl.morningRangeDesc',
    execution_mode: 'range',
    sign_at: '08:00',
    range_start: '08:00',
    range_end: '10:00',
    actions: [{ action: 1, text: '/sign' }],
  },
  {
    id: 'dice_checkin',
    nameKey: 'tasks.tpl.diceCheckin',
    descKey: 'tasks.tpl.diceCheckinDesc',
    execution_mode: 'fixed',
    sign_at: '09:30',
    actions: [
      { action: 1, text: '签到' },
      { action: 2, dice: '🎲' },
    ],
  },
  {
    id: 'listen_keyword',
    nameKey: 'tasks.tpl.listenKeyword',
    descKey: 'tasks.tpl.listenKeywordDesc',
    execution_mode: 'listen',
    sign_at: '00:00',
    actions: [
      {
        action: 8,
        keywords: ['签到成功', '已签到'],
        match_mode: 'contains',
        push_channel: 'telegram',
      },
    ],
  },
]

export type TemplateDraft = {
  name: string
  account_name: string
  account_names: string[]
  sign_at: string
  execution_mode: 'fixed' | 'range' | 'listen'
  range_start: string
  range_end: string
  random_seconds: number
  retry_count: number
  chats: Array<{
    chat_id: number
    name: string
    actions: RawTaskAction[]
    action_interval: number
  }>
}

export function getTemplateById(templateId: string): TaskTemplate | undefined {
  return BUILT_IN_TEMPLATES.find((t) => t.id === templateId)
}

export function buildPayloadFromTemplate(
  templateId: string,
  opts: { account_name: string; chat_id?: number; chat_name?: string; task_name?: string },
): TemplateDraft {
  const tpl = getTemplateById(templateId)
  if (!tpl) {
    throw new Error(`unknown template: ${templateId}`)
  }
  const account = opts.account_name || ''
  const chatId = opts.chat_id || 0
  return {
    name: opts.task_name || tpl.id,
    account_name: account,
    account_names: account ? [account] : [],
    sign_at: tpl.sign_at,
    execution_mode: tpl.execution_mode,
    range_start: tpl.range_start || '',
    range_end: tpl.range_end || '',
    random_seconds: 0,
    retry_count: 3,
    chats: [
      {
        chat_id: chatId,
        name: opts.chat_name || '',
        actions: tpl.actions.map((a) => ({ ...a })),
        action_interval: 1,
      },
    ],
  }
}

/**
 * 转为 TaskForm 可消费的 initialTask 形状。
 * chat_id 可为 0：表单打开后由用户选择真实会话再保存。
 */
export function buildSignTaskFromTemplate(
  templateId: string,
  opts: { account_name: string; task_name?: string },
): SignTask {
  const draft = buildPayloadFromTemplate(templateId, opts)
  const chats: SignTaskChat[] = draft.chats.map((c) => ({
    chat_id: c.chat_id,
    name: c.name,
    actions: c.actions,
    action_interval: c.action_interval,
  }))
  return {
    name: draft.name,
    account_name: draft.account_name,
    account_names: draft.account_names,
    sign_at: draft.sign_at,
    chats,
    random_seconds: draft.random_seconds,
    sign_interval: 1,
    enabled: true,
    execution_mode: draft.execution_mode,
    range_start: draft.range_start || undefined,
    range_end: draft.range_end || undefined,
    retry_count: draft.retry_count,
  }
}
