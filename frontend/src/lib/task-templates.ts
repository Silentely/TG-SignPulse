/**
 * 内置签到任务模板（前端草稿，保存时仍走创建 API）。
 * action 枚举与 task-form-utils / SupportAction 对齐。
 */

export type TaskTemplate = {
  id: string
  nameKey: string
  descKey: string
  execution_mode: 'fixed' | 'range' | 'listen'
  sign_at: string
  actions: Array<Record<string, unknown>>
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
    actions: Array<Record<string, unknown>>
    action_interval: number
  }>
}

export function buildPayloadFromTemplate(
  templateId: string,
  opts: { account_name: string; chat_id?: number; chat_name?: string; task_name?: string },
): TemplateDraft {
  const tpl = BUILT_IN_TEMPLATES.find((t) => t.id === templateId)
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
    range_start: '',
    range_end: '',
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
