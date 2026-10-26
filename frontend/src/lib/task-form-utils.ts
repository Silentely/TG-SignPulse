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
  99: 'custom_plugin',
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
    case 'custom_plugin':
      item.value = raw.plugin_name || ''
      item.plugin_name = raw.plugin_name || ''
      item.params = raw.params ? { ...raw.params } : {}
      item.mode = raw.mode || 'reactive'
      if (raw.timeout !== undefined) item.timeout = raw.timeout
      break
  }

  if (raw.continue_on_error !== undefined) {
    item.continue_on_error = Boolean(raw.continue_on_error)
  }
  if (raw.skip_if_matched) {
    item.skip_if_matched = String(raw.skip_if_matched)
  }
  if (raw.stop_flow_on_terminal !== undefined) {
    item.stop_flow_on_terminal = Boolean(raw.stop_flow_on_terminal)
  }
  if (raw.wait_for_reply) {
    item.wait_for_reply = true
    if (Array.isArray(raw.reply_success_patterns)) {
      item.reply_success_patterns = [...raw.reply_success_patterns]
    }
    if (Array.isArray(raw.reply_failure_patterns)) {
      item.reply_failure_patterns = [...raw.reply_failure_patterns]
    }
    if (raw.reply_timeout_seconds !== undefined) {
      item.reply_timeout_seconds = raw.reply_timeout_seconds
    }
    if (Array.isArray(raw.reply_retry_keywords)) {
      item.reply_retry_keywords = [...raw.reply_retry_keywords]
    }
    if (raw.reply_retry_interval !== undefined) {
      item.reply_retry_interval = raw.reply_retry_interval
    }
    if (raw.reply_retry_max_attempts !== undefined) {
      item.reply_retry_max_attempts = raw.reply_retry_max_attempts
    }
  }
  if (raw.semantic_result) {
    item.semantic_result = { ...raw.semantic_result }
  }
  if (raw.semantic_button) {
    item.semantic_button = { ...raw.semantic_button }
  }
  if (raw.semantic_triage) {
    item.semantic_triage = { ...raw.semantic_triage }
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
      result.bot_username = (action.value || '').trim().replace(/^@/, '')
      result.command_prefix = (action.commandPrefix || DEFAULT_CMD_PREFIX).trim()
      break
    case 'custom_plugin': {
      result.action = 99
      const rawName = action.value !== undefined && action.value !== '' ? action.value : (action.plugin_name || '')
      result.plugin_name = rawName.trim()
      result.params = action.params ? { ...action.params } : {}
      if (action.mode) result.mode = action.mode
      if (action.timeout !== undefined) result.timeout = action.timeout
      break
    }
  }

  // 从前一个 delay 动作获取延迟值
  if (prevAction?.type === 'delay' && prevAction.value) {
    result.delay = prevAction.value
  }

  if (action.continue_on_error) {
    result.continue_on_error = true
  }
  if (action.skip_if_matched && action.skip_if_matched.trim()) {
    result.skip_if_matched = action.skip_if_matched.trim()
  }
  if (action.stop_flow_on_terminal) {
    result.stop_flow_on_terminal = true
  }
  if (action.wait_for_reply) {
    result.wait_for_reply = true
    if (action.reply_success_patterns && action.reply_success_patterns.length > 0) {
      result.reply_success_patterns = [...action.reply_success_patterns]
    }
    if (action.reply_failure_patterns && action.reply_failure_patterns.length > 0) {
      result.reply_failure_patterns = [...action.reply_failure_patterns]
    }
    if (action.reply_timeout_seconds !== undefined) {
      result.reply_timeout_seconds = Number(action.reply_timeout_seconds)
    }
    if (action.reply_retry_keywords && action.reply_retry_keywords.length > 0) {
      result.reply_retry_keywords = [...action.reply_retry_keywords]
    }
    if (action.reply_retry_interval !== undefined) {
      result.reply_retry_interval = Number(action.reply_retry_interval)
    }
    if (action.reply_retry_max_attempts !== undefined) {
      result.reply_retry_max_attempts = Number(action.reply_retry_max_attempts)
    }
  }
  if (action.semantic_result) {
    result.semantic_result = { ...action.semantic_result }
  }
  if (action.semantic_button) {
    result.semantic_button = { ...action.semantic_button }
  }
  if (action.semantic_triage) {
    result.semantic_triage = { ...action.semantic_triage }
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

/**
 * 将带有 wait_for_reply 的动作列表转换为 PulseFlow steps 列表
 */
export function actionsToFlowSteps(actions: BuiltAction[]): any[] {
  const steps: any[] = []

  type PlanItem =
    | { kind: 'delay'; seconds: number; stepId: string }
    | { kind: 'action'; action: BuiltAction; stepId: string }
    | { kind: 'wait'; parentAction: BuiltAction; stepId: string }

  const plan: PlanItem[] = []
  for (let i = 0; i < actions.length; i++) {
    const act = actions[i]
    if (act.delay && parseFloat(act.delay) > 0) {
      plan.push({ kind: 'delay', seconds: parseFloat(act.delay), stepId: `step_${i}_delay` })
    }
    const actStepId = `step_${i}`
    plan.push({ kind: 'action', action: act, stepId: actStepId })
    if (act.wait_for_reply) {
      plan.push({ kind: 'wait', parentAction: act, stepId: `step_${i}_wait` })
    }
  }

  for (let idx = 0; idx < plan.length; idx++) {
    const item = plan[idx]
    const nextStepId = idx + 1 < plan.length ? plan[idx + 1].stepId : 'COMPLETE'

    if (item.kind === 'delay') {
      steps.push({
        step_id: item.stepId,
        node_type: 'delay',
        delay_seconds: item.seconds,
        next_step_id: nextStepId,
      })
    } else if (item.kind === 'action') {
      const act = item.action
      const actionTypeMap: Record<number, string> = {
        1: 'SEND_TEXT',
        2: 'SEND_DICE',
        3: 'CLICK_KEYBOARD_BY_TEXT',
        4: 'CHOOSE_OPTION_BY_IMAGE',
        5: 'REPLY_BY_CALCULATION_PROBLEM',
        6: 'REPLY_BY_IMAGE_RECOGNITION',
        7: 'CLICK_BUTTON_BY_CALCULATION_PROBLEM',
        9: 'TRIGGER_BOT_COMMAND',
        99: 'CUSTOM_PLUGIN',
      }
      const actTypeName = actionTypeMap[act.action] || 'SEND_TEXT'
      const params: Record<string, any> = {}
      if (act.text !== undefined) params.text = act.text
      if (act.dice !== undefined) params.dice = act.dice
      if (act.ai_prompt !== undefined) params.ai_prompt = act.ai_prompt
      if (act.bot_username !== undefined) params.bot_username = act.bot_username
      if (act.command_prefix !== undefined) params.command_prefix = act.command_prefix
      if (act.plugin_name !== undefined) params.plugin_name = act.plugin_name
      if (act.params !== undefined) params.params = act.params
      if (act.mode !== undefined) params.mode = act.mode

      const step: any = {
        step_id: item.stepId,
        node_type: 'action',
        action_type: actTypeName,
        params,
        next_step_id: nextStepId,
      }
      if (act.timeout) step.timeout_seconds = act.timeout
      if (act.skip_if_matched) step.skip_if = act.skip_if_matched
      if (act.continue_on_error) step.on_failure_step_id = nextStepId
      if (act.stop_flow_on_terminal) step.terminal_policy = 'stop_flow'
      steps.push(step)
    } else if (item.kind === 'wait') {
      const act = item.parentAction
      const successPatterns = act.reply_success_patterns && act.reply_success_patterns.length > 0
        ? [...act.reply_success_patterns]
        : ['出席率\\s*成功']
      const failurePatterns = act.reply_failure_patterns && act.reply_failure_patterns.length > 0
        ? [...act.reply_failure_patterns]
        : ['出席率\\s*失败', '签到失败', '操作失败']
      const timeout = act.reply_timeout_seconds !== undefined ? Number(act.reply_timeout_seconds) : 90
      const retryKeywords = act.reply_retry_keywords && act.reply_retry_keywords.length > 0
        ? [...act.reply_retry_keywords]
        : ['再试', '重试', '稍后', '人数较多', '繁忙', '请 10 秒后']
      const retryInterval = act.reply_retry_interval !== undefined ? Number(act.reply_retry_interval) : 10
      const maxRetries = act.reply_retry_max_attempts !== undefined ? Number(act.reply_retry_max_attempts) : 3

      const step: any = {
        step_id: item.stepId,
        node_type: 'wait_event',
        event_type: 'ANY',
        success_patterns: successPatterns,
        failure_patterns: failurePatterns,
        timeout_seconds: timeout,
        retry_keywords: retryKeywords,
        retry_interval: retryInterval,
        max_retries: maxRetries,
        next_step_id: nextStepId,
        on_failure_step_id: 'FAIL',
      }
      steps.push(step)
    }
  }

  return steps
}

/** 解析后端工作流 steps 列表为前端动作项（回显动作序列及等待回复配置） */
export function parseStepsToActions(steps: any[]): TaskActionItem[] | null {
  if (!Array.isArray(steps) || steps.length === 0) return null
  const items: TaskActionItem[] = []
  let i = 0
  while (i < steps.length) {
    const step = steps[i]
    if (!step || typeof step !== 'object') return null
    const ntype = String(step.node_type || 'action').toLowerCase()
    if (ntype === 'delay') {
      items.push({
        id: nextActionId(),
        type: 'delay',
        value: String(step.delay_seconds || step.seconds || 1),
        aiPrompt: '',
      })
      i++
      continue
    }
    if (ntype === 'action') {
      const actType = step.action_type || step.action || 1
      const params = step.params || step.config || {}
      let actionNum = 1
      if (typeof actType === 'string') {
        const at = actType.toUpperCase()
        if (at === 'SEND_TEXT' || at === '1') actionNum = 1
        else if (at === 'SEND_DICE' || at === '2') actionNum = 2
        else if (at === 'CLICK_KEYBOARD_BY_TEXT' || at === '3') actionNum = 3
        else if (at === 'CHOOSE_OPTION_BY_IMAGE' || at === '4') actionNum = 4
        else if (at === 'REPLY_BY_CALCULATION_PROBLEM' || at === '5') actionNum = 5
        else if (at === 'REPLY_BY_IMAGE_RECOGNITION' || at === '6') actionNum = 6
        else if (at === 'CLICK_BUTTON_BY_CALCULATION_PROBLEM' || at === '7') actionNum = 7
        else if (at === 'TRIGGER_BOT_COMMAND' || at === '9') actionNum = 9
        else if (at === 'CUSTOM_PLUGIN' || at === '99') actionNum = 99
      } else if (typeof actType === 'number') {
        actionNum = actType
      }
      const rawAct: RawTaskAction = {
        action: actionNum,
        text: params.text,
        dice: params.dice,
        ai_prompt: params.ai_prompt,
        bot_username: params.bot_username,
        command_prefix: params.command_prefix,
        plugin_name: params.plugin_name,
        params: params.params,
        mode: params.mode,
        timeout: step.timeout_seconds,
        continue_on_error: step.on_failure_step_id !== 'FAIL' && step.on_failure_step_id !== '_TERMINAL_FAIL' && !!step.on_failure_step_id,
        skip_if_matched: step.skip_if,
        stop_flow_on_terminal: step.terminal_policy === 'stop_flow',
      }
      const parsed = parseSingleAction(rawAct)
      if (parsed.length === 0) {
        i++
        continue
      }
      const actionItem = parsed[parsed.length - 1]

      // 检查后续紧邻节点是否为配套的 wait_event
      if (i + 1 < steps.length) {
        const nextStep = steps[i + 1]
        const nextNtype = String(nextStep.node_type || '').toLowerCase()
        if (nextNtype === 'wait_event') {
          actionItem.wait_for_reply = true
          actionItem.reply_success_patterns = Array.isArray(nextStep.success_patterns) && nextStep.success_patterns.length > 0
            ? [...nextStep.success_patterns]
            : (Array.isArray(nextStep.filter_patterns) && nextStep.filter_patterns.length > 0 ? [...nextStep.filter_patterns] : [])
          actionItem.reply_failure_patterns = Array.isArray(nextStep.failure_patterns)
            ? [...nextStep.failure_patterns]
            : []
          actionItem.reply_timeout_seconds = nextStep.timeout_seconds !== undefined
            ? Number(nextStep.timeout_seconds)
            : 90
          if (Array.isArray(nextStep.retry_keywords)) {
            actionItem.reply_retry_keywords = [...nextStep.retry_keywords]
          }
          if (nextStep.retry_interval !== undefined) {
            actionItem.reply_retry_interval = Number(nextStep.retry_interval)
          }
          if (nextStep.max_retries !== undefined) {
            actionItem.reply_retry_max_attempts = Number(nextStep.max_retries)
          }
          i++ // 跳过已配对的 wait_event 节点
        }
      }
      items.push(actionItem)
      i++
      continue
    }
    // 遇到其他复杂控制节点则不属于 actions 自动升级模式
    return null
  }
  return items.length > 0 ? items : null
}
