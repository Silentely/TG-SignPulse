/**
 * 签到列表本地筛选：模式 + 搜索关键词（纯函数，便于单测）。
 */

export type TaskListModeFilter = 'all' | 'listen' | 'scheduled'

export type TaskListFilterItem = {
  name: string
  targetStr: string
  scheduleMode: string
  lastRunStr: string
  isListenMode: boolean
}

export function filterTasksByModeAndQuery<T extends TaskListFilterItem>(
  tasks: T[],
  modeFilter: TaskListModeFilter,
  searchQuery: string,
): T[] {
  let list = tasks
  if (modeFilter === 'listen') {
    list = list.filter((task) => task.isListenMode)
  } else if (modeFilter === 'scheduled') {
    list = list.filter((task) => !task.isListenMode)
  }
  const q = searchQuery.trim().toLowerCase()
  if (!q) return list
  return list.filter(
    (task) =>
      task.name.toLowerCase().includes(q) ||
      task.targetStr.toLowerCase().includes(q) ||
      task.scheduleMode.toLowerCase().includes(q) ||
      task.lastRunStr.toLowerCase().includes(q),
  )
}

/** 是否存在激活中的列表筛选（搜索 / 模式 / 账号深链） */
export function hasActiveListFilters(
  searchQuery: string,
  modeFilter: TaskListModeFilter,
  accountFilter?: string | null,
): boolean {
  return (
    searchQuery.trim().length > 0 ||
    modeFilter !== 'all' ||
    !!(accountFilter && String(accountFilter).trim())
  )
}
