import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import {
  flushPromises,
  mockI18nPassthrough,
  mountComposable,
} from './composable-test-utils'

const toastSpy = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  show: vi.fn(),
}))
const confirmMock = vi.hoisted(() => ({
  confirm: vi.fn(async () => true),
}))
const routeMocks = vi.hoisted(() => {
  const state = {
    name: 'logs',
    query: {
      account: 'acc-q',
      task: 'task-q',
      category: 'timeout',
      at: '2026-07-01T10:00:00',
    } as Record<string, string | undefined>,
  }
  const replace = vi.fn(async (loc: { name?: string; query?: Record<string, unknown> }) => {
    if (loc.name) state.name = loc.name
    if (loc.query) state.query = { ...loc.query } as Record<string, string | undefined>
  })
  return {
    state,
    route: {
      get name() {
        return state.name
      },
      get query() {
        return state.query
      },
    },
    router: { replace, push: replace },
  }
})
const api = vi.hoisted(() => ({
  getTaskHistoryLogs: vi.fn(),
  getTaskHistoryLogDetail: vi.fn(),
  getLoginAuditLogs: vi.fn(),
  listAccounts: vi.fn(),
  clearTaskHistoryLogs: vi.fn(),
  clearLoginAuditLogs: vi.fn(),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
}))
vi.mock('../composables/useConfirm', () => ({
  useConfirm: () => confirmMock,
}))
vi.mock('vue-router', () => ({
  useRoute: () => routeMocks.route,
  useRouter: () => routeMocks.router,
}))
vi.mock('../lib/api', () => api)

import { useLogsPage } from '../composables/useLogsPage'
import { useAuthStore } from '../stores/auth'
import type { TaskLogUiItem } from '../lib/types'

// 让 route mock 的 query 具备 Vue 响应性，覆盖真实路由变化触发的筛选同步。
const reactiveRouteQuery = ref(routeMocks.state.query)
Object.defineProperty(routeMocks.state, 'query', {
  configurable: true,
  get: () => reactiveRouteQuery.value,
  set: (value: Record<string, string | undefined>) => {
    reactiveRouteQuery.value = value
  },
})

describe('useLogsPage (route + mount)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.confirm.mockResolvedValue(true)
    useAuthStore().setToken('tok')
    routeMocks.state.query = {
      account: 'acc-q',
      task: 'task-q',
      category: 'timeout',
      at: '2026-07-01T10:00:00',
    }
    api.listAccounts.mockResolvedValue({ accounts: [{ name: 'acc-q' }, { name: 'acc-2' }] })
    api.getTaskHistoryLogs.mockResolvedValue([
      {
        id: 1,
        task_name: 'task-q',
        account_name: 'acc-q',
        created_at: '2026-07-01T10:00:00',
        success: false,
        message: 'timeout',
        failure_category: 'timeout',
        flow_line_count: 2,
      },
      {
        id: 2,
        task_name: 'other',
        account_name: 'acc-2',
        created_at: '2026-07-01T11:00:00',
        success: true,
        message: 'ok',
        failure_category: '',
        flow_line_count: 0,
      },
    ])
    api.getTaskHistoryLogDetail.mockResolvedValue({
      flow_logs: ['a', 'b'],
      message: 'detail',
    })
    api.getLoginAuditLogs.mockResolvedValue([])
    api.clearTaskHistoryLogs.mockResolvedValue({ cleared: 3 })
  })

  it('onMounted applies route filters, loads logs and opens deep-linked detail', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()

    expect(result.filterAccount.value).toBe('acc-q')
    expect(result.filterTask.value).toBe('task-q')
    expect(result.filterCategory.value).toBe('timeout')
    expect(result.filterStatus.value).toBe('error')
    expect(api.getTaskHistoryLogs).toHaveBeenCalledWith(
      'tok',
      expect.objectContaining({ account_name: 'acc-q' }),
    )
    expect(result.selectedLog.value?.task).toBe('task-q')
    expect(api.getTaskHistoryLogDetail).toHaveBeenCalled()
    expect(result.pageLoading.value).toBe(false)
    unmount()
  })

  it('reopens the selected detail when a same-page deep link changes', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    try {
      await flushPromises()
      expect(result.selectedLog.value?.task).toBe('task-q')

      api.getTaskHistoryLogs.mockResolvedValue([
        {
          id: 2,
          task_name: 'other',
          account_name: 'acc-q',
          created_at: '2026-07-01T11:00:00',
          success: true,
          message: 'second log',
          failure_category: '',
          flow_line_count: 0,
        },
      ])
      api.getTaskHistoryLogDetail.mockResolvedValueOnce({
        flow_logs: ['second'],
        message: 'second detail',
      })

      await routeMocks.router.replace({
        name: 'logs',
        query: {
          account: 'acc-q',
          task: 'other',
          at: '2026-07-01T11:00:00',
        },
      })
      await flushPromises()

      expect(result.selectedLog.value?.task).toBe('other')
      expect(result.logDetail.value?.message).toBe('second detail')
    } finally {
      unmount()
    }
  })

  it('client filters by task/status/category', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()

    // category=timeout 已从路由应用，只保留失败且 category 匹配
    expect(result.logs.value.every((l) => l.status === 'error')).toBe(true)
    result.filterCategory.value = ''
    result.filterStatus.value = 'success'
    result.filterTask.value = 'other'
    expect(result.logs.value).toHaveLength(1)
    expect(result.logs.value[0].task).toBe('other')
    unmount()
  })

  it('clearCategoryFilter strips route category query', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    result.clearCategoryFilter()
    expect(result.filterCategory.value).toBe('')
    expect(routeMocks.router.replace).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'logs',
        query: expect.not.objectContaining({ category: 'timeout' }),
      }),
    )
    unmount()
  })

  it('clears route-driven filters when the deep-link query is removed', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()

    await routeMocks.router.replace({ name: 'logs', query: {} })
    await flushPromises()

    expect(result.filterAccount.value).toBe('')
    expect(result.filterTask.value).toBe('')
    expect(result.filterCategory.value).toBe('')
    expect(result.filterStatus.value).toBe('')
    unmount()
  })

  it('reports active filters and clears local plus deep-link state together', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()

    result.filterTask.value = 'missing'
    result.filterAccount.value = 'acc-2'
    result.filterDate.value = '2026-07-02'
    result.filterStatus.value = 'success'
    result.filterCategory.value = 'timeout'
    expect(result.hasActiveFilters.value).toBe(true)

    await result.clearFilters()
    await flushPromises()

    expect(result.hasActiveFilters.value).toBe(false)
    expect(result.filterTask.value).toBe('')
    expect(result.filterAccount.value).toBe('')
    expect(result.filterDate.value).toBe('')
    expect(result.filterStatus.value).toBe('')
    expect(result.filterCategory.value).toBe('')
    expect(routeMocks.router.replace).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'logs',
        query: expect.not.objectContaining({
          account: 'acc-q',
          task: 'task-q',
          category: 'timeout',
          at: '2026-07-01T10:00:00',
        }),
      }),
    )
    unmount()
  })

  it('handleClear clears task logs after confirm', async () => {
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    await result.handleClear()
    expect(api.clearTaskHistoryLogs).toHaveBeenCalledWith('tok')
    // rawTaskLogs 未导出；清空后 logs computed 应为空
    expect(result.logs.value).toEqual([])
    expect(toastSpy.success).toHaveBeenCalled()
    unmount()
  })

  it('handleClear aborts when confirm false', async () => {
    confirmMock.confirm.mockResolvedValueOnce(false)
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    await result.handleClear()
    expect(api.clearTaskHistoryLogs).not.toHaveBeenCalled()
    unmount()
  })

  it('switching to login tab loads audit logs', async () => {
    api.getLoginAuditLogs.mockResolvedValue([
      {
        id: 9,
        created_at: '2026-07-01T12:00:00',
        username: 'admin',
        ip_address: '1.1.1.1',
        success: true,
        detail: null,
      },
    ])
    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    result.activeTab.value = 'login'
    await flushPromises()
    expect(api.getLoginAuditLogs).toHaveBeenCalled()
    expect(result.loginLogs.value).toHaveLength(1)
    expect(result.loginLogs.value[0].username).toBe('admin')
    unmount()
  })

  it('discards stale task-log response when a newer load supersedes it', async () => {
    routeMocks.state.query = {} // 避免路由筛选在挂载时额外触发加载
    let resolveStale!: (v: unknown) => void
    const stalePromise = new Promise((resolve) => {
      resolveStale = resolve
    })
    api.getTaskHistoryLogs
      .mockReturnValueOnce(stalePromise) // 挂载时的首次请求（挂起）
      .mockResolvedValueOnce([
        {
          id: 2,
          task_name: 'fresh',
          account_name: 'acc-2',
          created_at: '2026-07-02T00:00:00',
          success: true,
          message: 'ok',
          failure_category: '',
          flow_line_count: 0,
        },
      ])

    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    // 首次请求仍挂起时再触发一次加载（等价于筛选变化）
    await result.loadLogs()
    await flushPromises()
    expect(result.logs.value.map((l) => l.task)).toEqual(['fresh'])

    // 迟到的旧响应不得覆盖新数据
    resolveStale([
      {
        id: 1,
        task_name: 'stale',
        account_name: 'acc-q',
        created_at: '2026-07-01T00:00:00',
        success: false,
        message: 'old',
        failure_category: 'timeout',
        flow_line_count: 1,
      },
    ])
    await flushPromises()
    expect(result.logs.value.map((l) => l.task)).toEqual(['fresh'])
    unmount()
  })

  it('keeps page loading while an older request settles before the newest one', async () => {
    routeMocks.state.query = {}
    let resolveOld!: (value: unknown) => void
    let resolveNewest!: (value: unknown) => void
    const oldPromise = new Promise((resolve) => {
      resolveOld = resolve
    })
    const newestPromise = new Promise((resolve) => {
      resolveNewest = resolve
    })
    api.getTaskHistoryLogs
      .mockReturnValueOnce(oldPromise)
      .mockReturnValueOnce(newestPromise)

    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()
    const newestLoad = result.loadLogs()
    await flushPromises()

    resolveOld([])
    await flushPromises()
    expect(result.pageLoading.value).toBe(true)

    resolveNewest([])
    await newestLoad
    await flushPromises()
    expect(result.pageLoading.value).toBe(false)
    unmount()
  })

  it('discards stale log-detail response when another log is selected', async () => {
    routeMocks.state.query = { account: 'acc-q' } // 去掉 task/at，避免挂载自动打开详情
    let resolveStale!: (v: unknown) => void
    const stalePromise = new Promise((resolve) => {
      resolveStale = resolve
    })
    api.getTaskHistoryLogDetail
      .mockReturnValueOnce(stalePromise) // 先点 A（挂起）
      .mockResolvedValueOnce({ flow_logs: ['B'], message: 'B detail' }) // 再点 B（立即返回）

    const { result, unmount } = mountComposable(() => useLogsPage())
    await flushPromises()

    const base = {
      time: 'x',
      account: 'acc-q',
      status: 'error' as const,
      text: 'a',
      flow_line_count: 1,
    }
    const logA: TaskLogUiItem = { ...base, id: 1, created_at: '2026-07-01T10:00:00', task: 'task-q', failure_category: 'timeout' }
    const logB: TaskLogUiItem = { ...base, id: 2, created_at: '2026-07-01T11:00:00', task: 'other', failure_category: undefined }

    const pA = result.openLogDetail(logA)
    const pB = result.openLogDetail(logB)
    await pB
    await flushPromises()
    expect(result.logDetail.value?.message).toBe('B detail')

    // 迟到的 A 详情不得覆盖当前选中的 B
    resolveStale({ flow_logs: ['A'], message: 'A detail' })
    await pA
    await flushPromises()
    expect(result.logDetail.value?.message).toBe('B detail')
    expect(result.detailLoading.value).toBe(false)
    unmount()
  })
})
