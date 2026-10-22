import { describe, expect, it } from 'vitest'

describe('Tasks DeepLink logic', () => {
  it('opens history tab when tab=logs or tab=suggestions', () => {
    const tasks = [
      { name: 'daily', isListenMode: false },
      { name: 'monitor', isListenMode: true },
    ]

    const resolveDeepLink = (query: { tab?: string; task?: string }) => {
      const tab = String(query.tab || '').trim()
      const taskQ = (query.task || '').trim()
      if (!taskQ || !tasks.length) return null
      if (tab !== 'hits' && tab !== 'logs' && tab !== 'suggestions') return null
      const found = tasks.find((t) => t.name === taskQ)
      if (!found) return null
      if (tab === 'hits' && !found.isListenMode) return null
      const targetTab = tab === 'hits' ? 'hits' : 'history'
      return { task: found, tab: targetTab, open: true }
    }

    // tab=logs on normal task
    expect(resolveDeepLink({ tab: 'logs', task: 'daily' })).toEqual({
      task: tasks[0],
      tab: 'history',
      open: true,
    })

    // tab=suggestions on listen task
    expect(resolveDeepLink({ tab: 'suggestions', task: 'monitor' })).toEqual({
      task: tasks[1],
      tab: 'history',
      open: true,
    })

    // tab=hits on listen task
    expect(resolveDeepLink({ tab: 'hits', task: 'monitor' })).toEqual({
      task: tasks[1],
      tab: 'hits',
      open: true,
    })

    // tab=hits on normal task should be ignored
    expect(resolveDeepLink({ tab: 'hits', task: 'daily' })).toBeNull()

    // unknown tab ignored
    expect(resolveDeepLink({ tab: 'other', task: 'daily' })).toBeNull()
  })
})
