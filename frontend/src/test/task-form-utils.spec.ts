import { describe, it, expect, beforeEach } from 'vitest'
import {
  parseActions,
  parseSingleAction,
  buildSingleAction,
  buildActions,
  nextActionId,
  resetActionIdCounter,
  debounce,
} from '../lib/task-form-utils'
import type { RawTaskAction, TaskActionItem } from '../lib/types'

describe('nextActionId', () => {
  beforeEach(() => resetActionIdCounter())

  it('返回递增的唯一 ID', () => {
    const id1 = nextActionId()
    const id2 = nextActionId()
    expect(id2).toBeGreaterThan(id1)
  })

  it('重置后从 1 开始', () => {
    nextActionId()
    nextActionId()
    resetActionIdCounter()
    expect(nextActionId()).toBe(1)
  })
})

describe('parseSingleAction', () => {
  beforeEach(() => resetActionIdCounter())

  it('解析 send_text 动作 (action=1)', () => {
    const raw: RawTaskAction = { action: 1, text: '签到' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('send_text')
    expect(result[0].value).toBe('签到')
  })

  it('解析 send_dice 动作 (action=2)', () => {
    const raw: RawTaskAction = { action: 2, dice: '🎲' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('send_dice')
    expect(result[0].value).toBe('🎲')
  })

  it('解析 click_text_button 动作 (action=3)', () => {
    const raw: RawTaskAction = { action: 3, text: '确认' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('click_text_button')
    expect(result[0].value).toBe('确认')
  })

  it('解析 vision_click 动作 (action=4)', () => {
    const raw: RawTaskAction = { action: 4, ai_prompt: '点击图片中的按钮' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('vision_click')
    expect(result[0].aiPrompt).toBe('点击图片中的按钮')
  })

  it('解析 calc_send 动作 (action=5)', () => {
    const raw: RawTaskAction = { action: 5, ai_prompt: '计算 1+1' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('calc_send')
  })

  it('解析 bot_cmd 动作 (action=9)', () => {
    const raw: RawTaskAction = { action: 9, bot_username: 'mybot', command_prefix: '/go' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('bot_cmd')
    expect(result[0].value).toBe('mybot')
    expect(result[0].commandPrefix).toBe('/go')
  })

  it('bot_cmd 使用默认 command_prefix', () => {
    const raw: RawTaskAction = { action: 9, bot_username: 'mybot' }
    const result = parseSingleAction(raw)
    expect(result[0].commandPrefix).toBe('/start')
  })

  it('解析带 delay 的动作生成两个项', () => {
    const raw: RawTaskAction = { action: 1, text: 'hello', delay: 5 }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(2)
    expect(result[0].type).toBe('delay')
    expect(result[0].value).toBe('5')
    expect(result[1].type).toBe('send_text')
    expect(result[1].value).toBe('hello')
  })

  it('忽略未知动作类型', () => {
    const raw: RawTaskAction = { action: 999, text: 'test' }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(0)
  })

  it('忽略无 delay 值的 delay 字段', () => {
    const raw: RawTaskAction = { action: 1, text: 'test', delay: 0 }
    const result = parseSingleAction(raw)
    expect(result).toHaveLength(1)
    expect(result[0].type).toBe('send_text')
  })
})

describe('parseActions', () => {
  beforeEach(() => resetActionIdCounter())

  it('解析多个动作', () => {
    const raw: RawTaskAction[] = [
      { action: 1, text: '签到' },
      { action: 2, dice: '🎲' },
    ]
    const result = parseActions(raw)
    expect(result).toHaveLength(2)
    expect(result[0].type).toBe('send_text')
    expect(result[1].type).toBe('send_dice')
  })

  it('空数组返回空', () => {
    expect(parseActions([])).toHaveLength(0)
  })

  it('混合 delay 和动作', () => {
    const raw: RawTaskAction[] = [
      { action: 1, text: 'hello', delay: 3 },
      { action: 2 },
    ]
    const result = parseActions(raw)
    expect(result).toHaveLength(3)  // delay + send_text + send_dice
    expect(result[0].type).toBe('delay')
    expect(result[1].type).toBe('send_text')
    expect(result[2].type).toBe('send_dice')
  })
})

describe('buildSingleAction', () => {
  it('send_text 转换为 action=1', () => {
    const item: TaskActionItem = { id: 1, type: 'send_text', value: '签到', aiPrompt: '' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 1, text: '签到' })
  })

  it('send_dice 转换为 action=2', () => {
    const item: TaskActionItem = { id: 1, type: 'send_dice', value: '', aiPrompt: '' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 2, dice: '🎲' })
  })

  it('send_dice 使用自定义 emoji', () => {
    const item: TaskActionItem = { id: 1, type: 'send_dice', value: '🎯', aiPrompt: '' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 2, dice: '🎯' })
  })

  it('bot_cmd 转换为 action=9', () => {
    const item: TaskActionItem = { id: 1, type: 'bot_cmd', value: 'mybot', aiPrompt: '', commandPrefix: '/go' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 9, bot_username: 'mybot', command_prefix: '/go' })
  })

  it('delay 返回 null', () => {
    const item: TaskActionItem = { id: 1, type: 'delay', value: '5', aiPrompt: '' }
    expect(buildSingleAction(item)).toBeNull()
  })

  it('从前一个 delay 动作获取延迟值', () => {
    const prev: TaskActionItem = { id: 1, type: 'delay', value: '3', aiPrompt: '' }
    const curr: TaskActionItem = { id: 2, type: 'send_text', value: 'hello', aiPrompt: '' }
    const result = buildSingleAction(curr, prev)
    expect(result?.delay).toBe('3')
  })

  it('vision_click 无 aiPrompt 时不设置 ai_prompt', () => {
    const item: TaskActionItem = { id: 1, type: 'vision_click', value: '', aiPrompt: '' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 4 })
    expect(result).not.toHaveProperty('ai_prompt')
  })

  it('vision_click 有 aiPrompt 时设置 ai_prompt', () => {
    const item: TaskActionItem = { id: 1, type: 'vision_click', value: '', aiPrompt: '点击按钮' }
    const result = buildSingleAction(item)
    expect(result).toEqual({ action: 4, ai_prompt: '点击按钮' })
  })
})

describe('buildActions', () => {
  it('过滤 delay 动作', () => {
    const items: TaskActionItem[] = [
      { id: 1, type: 'delay', value: '3', aiPrompt: '' },
      { id: 2, type: 'send_text', value: 'hello', aiPrompt: '' },
    ]
    const result = buildActions(items)
    expect(result).toHaveLength(1)
    expect(result[0].action).toBe(1)
    expect(result[0].delay).toBe('3')
  })

  it('空数组返回空', () => {
    expect(buildActions([])).toHaveLength(0)
  })
})

describe('debounce', () => {
  it('延迟执行函数', async () => {
    let count = 0
    const fn = debounce(() => { count++ }, 100)
    fn()
    fn()
    fn()
    expect(count).toBe(0)
    await new Promise(r => setTimeout(r, 150))
    expect(count).toBe(1)
  })
})
