/**
 * TaskForm 核心数据转换逻辑
 * 从 TaskForm.vue 提取的纯函数，便于单元测试和调试
 */

import type { TaskActionItem, RawTaskAction, BuiltAction, TaskActionType } from './types'

/** 后端动作类型 ID → 前端类型名映射 */
const ACTION_TYPE_MAP: Record<number, TaskActionType> = {
  1: 'send_text',
  2: 'send_dice',
  3: 'click_text_button',
  4: 'vision_click',
  5: 'calc_send',
  6: 'vision_send',
  7: 'calc_click',
  9: 'bot_cmd',
}

const DEFAULT_CMD_PREFIX = '/start'

let _actionIdCounter = 0

/** 生成唯一的动作 ID（替代 Date.now()+Math.random()） */
export function nextActionId(): number {
  return ++_actionIdCounter
}

/** 重置 ID 计数器（仅用于测试） */
export function resetActionIdCounter(): void {
  _actionIdCounter = 0
}

/** 将单个后端动作转换为前端动作项 */
export function parseSingleAction(raw: RawTaskAction): TaskActionItem[] {
  const items: TaskActionItem[] = []

  if (raw.delay) {
    items.push({
      id: nextActionId(),
      type: 'delay',
      value: String(raw.delay),
      aiPrompt: '',
    })
  }

  const type = ACTION_TYPE_MAP[raw.action]
  if (!type) return items

  const item: TaskActionItem = {
    id: nextActionId(),
    type,
    value: '',
    aiPrompt: '',
  }

  switch (type) {
    case 'send_text':
    case 'click_text_button':
      item.value = raw.text || ''
      break
    case 'send_dice':
      item.value = raw.dice || ''
      break
    case 'bot_cmd':
      item.value = raw.bot_username || ''
      item.commandPrefix = raw.command_prefix || DEFAULT_CMD_PREFIX
      break
    case 'vision_click':
    case 'calc_send':
    case 'vision_send':
    case 'calc_click':
      item.aiPrompt = raw.ai_prompt || ''
      break
  }

  items.push(item)
  return items
}

/** 解析后端动作列表为前端动作项 */
export function parseActions(rawActions: RawTaskAction[]): TaskActionItem[] {
  return rawActions.flatMap(parseSingleAction)
}

/** 将单个前端动作项转换为后端动作 */
export function buildSingleAction(
  action: TaskActionItem,
  prevAction?: TaskActionItem,
): BuiltAction | null {
  if (action.type === 'delay') return null

  const result: BuiltAction = { action: 0 }

  switch (action.type) {
    case 'send_text':
      result.action = 1
      result.text = action.value
      break
    case 'send_dice':
      result.action = 2
      result.dice = action.value || '🎲'
      break
    case 'click_text_button':
      result.action = 3
      result.text = action.value
      break
    case 'vision_click':
      result.action = 4
      if (action.aiPrompt) result.ai_prompt = action.aiPrompt
      break
    case 'calc_send':
      result.action = 5
      if (action.aiPrompt) result.ai_prompt = action.aiPrompt
      break
    case 'vision_send':
      result.action = 6
      if (action.aiPrompt) result.ai_prompt = action.aiPrompt
      break
    case 'calc_click':
      result.action = 7
      if (action.aiPrompt) result.ai_prompt = action.aiPrompt
      break
    case 'bot_cmd':
      result.action = 9
      result.bot_username = action.value
      result.command_prefix = action.commandPrefix || DEFAULT_CMD_PREFIX
      break
  }

  // 从前一个 delay 动作获取延迟值
  if (prevAction?.type === 'delay' && prevAction.value) {
    result.delay = prevAction.value
  }

  return result
}

/** 将前端动作列表构建为后端动作列表 */
export function buildActions(actions: TaskActionItem[]): BuiltAction[] {
  const result: BuiltAction[] = []
  for (let i = 0; i < actions.length; i++) {
    const built = buildSingleAction(actions[i], i > 0 ? actions[i - 1] : undefined)
    if (built) result.push(built)
  }
  return result
}

/** 简单防抖函数 */
export function debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout>
  return ((...args: unknown[]) => {
    clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }) as T
}
