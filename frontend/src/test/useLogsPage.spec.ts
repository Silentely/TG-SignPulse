import { beforeEach, describe, expect, it, vi } from 'vitest'
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
})
