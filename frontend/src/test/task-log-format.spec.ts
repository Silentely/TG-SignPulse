import { describe, expect, it } from 'vitest'
import {
  buildTaskLogViewModel,
  formatLastTargetMessage,
  normalizeFlowLogLines,
  sanitizeFlowLogLine,
} from '../lib/task-log-format'

describe('sanitizeFlowLogLine', () => {
  it('去除时间戳前缀', () => {
    expect(sanitizeFlowLogLine('2026-01-01 12:00:00 - 任务开始')).toBe('任务开始')
  })

  it('去除账户任务上下文前缀', () => {
    expect(sanitizeFlowLogLine('账户「a」 - 任务「t」: 开始登录')).toBe('开始登录')
  })

  it('跳过装饰线与噪声行', () => {
    expect(sanitizeFlowLogLine('══════')).toBe('')
    expect(sanitizeFlowLogLine('Message:')).toBe('')
    expect(sanitizeFlowLogLine('Chat ID: 123')).toBe('')
  })
})

describe('normalizeFlowLogLines', () => {
  it('去重并扁平化多行', () => {
    const result = normalizeFlowLogLines([
      '2026-01-01 12:00:00 - 开始登录',
      '开始登录',
      '确认对象\n发送文本',
    ])
    expect(result).toEqual(['开始登录', '确认对象', '发送文本'])
  })

  it('空输入返回空数组', () => {
    expect(normalizeFlowLogLines(undefined)).toEqual([])
    expect(normalizeFlowLogLines([])).toEqual([])
  })
})

describe('formatLastTargetMessage', () => {
  it('按 · 与换行拆分', () => {
    expect(formatLastTargetMessage('a · b\nc')).toEqual(['a', 'b', 'c'])
  })

  it('空值返回空数组', () => {
    expect(formatLastTargetMessage('')).toEqual([])
    expect(formatLastTargetMessage(undefined)).toEqual([])
  })
})

describe('buildTaskLogViewModel', () => {
  it('提取最后目标消息并分组初始化/流程', () => {
    const vm = buildTaskLogViewModel(
      [
        '开始登录',
        '开始执行任务对象: @bot',
        '第 1/1 步执行完成：发送文本消息',
        '任务对象最后一条消息: 签到成功 +10',
      ],
      undefined
    )
    expect(vm.lastTargetMessage).toContain('签到成功')
    expect(vm.blocks.some((b) => b.kind === 'section')).toBe(true)
  })

  it('优先使用显式 lastTargetMessage', () => {
    const vm = buildTaskLogViewModel(['开始登录'], '显式结果')
    expect(vm.lastTargetMessage).toBe('显式结果')
  })

  it('错误行作为独立 line block', () => {
    const vm = buildTaskLogViewModel(['任务执行出错: timeout', '任务最终状态: failed'])
    const lines = vm.blocks.filter((b) => b.kind === 'line').map((b) => b.kind === 'line' ? b.text : '')
    expect(lines.some((t) => t.includes('出错'))).toBe(true)
    expect(lines.some((t) => t.includes('最终状态'))).toBe(true)
  })

  it('展示后端 TaskLogHandler 捕获的真实过程日志形态', () => {
    // 模拟 flow_logs：外壳行 + runtime self.log 经 Handler 格式化后的行
    const flowLogs = [
      '[run_id=61285738792b48f9a109054caca9f0eb]',
      '开始执行任务: emby-厂妹 (账号: dahao)',
      '消息更新监听: 开启',
      '2026-07-18 20:54:20,896 - 账户「dahao」- 任务「emby-厂妹」: 开始登录...',
      '2026-07-18 20:54:23,253 - 账户「dahao」- 任务「emby-厂妹」: Preheated peer with cached username: 1429576125 -> @EmbyPublicBot',
      '2026-07-18 20:54:23,518 - 账户「dahao」- 任务「emby-厂妹」: 开始第 1/3 次脚本流程尝试',
      '2026-07-18 20:54:23,731 - 账户「dahao」- 任务「emby-厂妹」: 第 2/2 步将在 1 秒后执行：识图后点按钮',
      '2026-07-18 20:54:34,505 - 账户「dahao」- 任务「emby-厂妹」: 点击完成',
      '2026-07-18 20:54:34,806 - 账户「dahao」- 任务「emby-厂妹」: 第 2/2 步执行完成：识图后点按钮',
      '任务执行完成',
    ]
    const vm = buildTaskLogViewModel(flowLogs)
    const flat = vm.blocks
      .flatMap((b) => {
        if (b.kind === 'line') return [b.text]
        return [b.title, ...b.items]
      })
      .join('\n')

    // 外壳与登录
    expect(flat).toContain('开始执行任务')
    expect(flat).toContain('执行登录')
    // 流程分段
    expect(flat).toMatch(/开始第 1\/3 次脚本流程尝试/)
    expect(flat).toContain('点击完成')
    // 步骤完成应出现在 section items 中（识图后点按钮原文）
    expect(flat).toContain('识图后点按钮')
    expect(flat).toContain('任务执行完成')
  })
})
