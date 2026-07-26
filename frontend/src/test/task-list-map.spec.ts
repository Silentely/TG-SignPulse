import { describe, it, expect } from 'vitest'
import {
  formatTaskListDate,
  mapSignTaskToListFields,
  resolveTaskAccountName,
  resolveTaskRealAccounts,
  withModeIcon,
} from '../lib/task-list-map'
import type { SignTask } from '../lib/api'

const labels = {
  noTarget: '无目标',
  listenMode: '监听',
  notExecuted: '未执行',
  continuousRunning: '持续运行',
  paused: '已暂停',
  success: '成功',
  failed: '失败',
}

function baseTask(over: Partial<SignTask> = {}): SignTask {
  return {
    name: 't1',
    account_name: 'acc',
    account_names: ['acc'],
    sign_at: '08:00',
    execution_mode: 'fixed',
    chats: [{ chat_id: 1, name: '群' }],
    enabled: true,
    ...over,
  } as SignTask
}

describe('task-list-map', () => {
  it('resolves account name skipping wildcard', () => {
    expect(resolveTaskAccountName({ account_name: '*', account_names: ['*', 'a'] })).toBe('a')
    expect(resolveTaskRealAccounts(baseTask({ account_names: ['*'] }), ['x', 'y'])).toEqual(['x', 'y'])
  })

  it('maps fixed and listen tasks', () => {
    const fixed = mapSignTaskToListFields(baseTask(), labels)
    expect(fixed.scheduleMode).toBe('08:00')
    expect(fixed.modeIconKind).toBe('clock')
    expect(fixed.targetStr).toBe('群')

    const listen = mapSignTaskToListFields(
      baseTask({ execution_mode: 'listen', last_run: undefined, enabled: true }),
      labels,
    )
    expect(listen.isListenMode).toBe(true)
    expect(listen.lastRunStr).toBe('持续运行')
    expect(listen.modeIconKind).toBe('radio')
  })

  it('withModeIcon drops kind field', () => {
    const fields = mapSignTaskToListFields(baseTask(), labels)
    const icon = { name: 'Clock' } as any
    const ui = withModeIcon(fields, icon)
    expect(ui.modeIcon).toBe(icon)
    expect((ui as any).modeIconKind).toBeUndefined()
  })

  it('formatTaskListDate returns dash for empty', () => {
    expect(formatTaskListDate('')).toBe('-')
  })
})
