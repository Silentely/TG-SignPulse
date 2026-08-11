import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  MockEventSource,
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
const notifyApiErrorSpy = vi.hoisted(() => vi.fn())

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  listSignTasks: vi.fn(),
  getRecentAccountLogs: vi.fn(),
  listScheduledJobs: vi.fn(),
  listActiveSignTaskRuns: vi.fn(),
  listKeywordHits: vi.fn(),
  listAccountStatusCheckJobs: vi.fn(),
}))

const activeRunsStoreMock = vi.hoisted(() => {
  const store = {
    runs: { value: [] as unknown[] },
    refresh: vi.fn(async () => {
      const res = await api.listActiveSignTaskRuns('tok')
      store.runs.value = res?.runs || []
      return true
    }),
    ensurePolling: vi.fn(),
    acquire: vi.fn(),
    release: vi.fn(),
  }
  return store
})

const pollState = vi.hoisted(() => ({
  ticks: [] as Array<() => Promise<void>>,
  stops: [] as Array<ReturnType<typeof vi.fn>>,
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
}))
vi.mock('../lib/notify', () => ({
  notifyApiError: notifyApiErrorSpy,
}))
vi.mock('../lib/api', () => api)
vi.mock('../stores/activeRuns', () => ({
  useActiveRunsStore: () => activeRunsStoreMock,
}))
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => store,
  }
})
vi.mock('../lib/chain-poll', () => ({
  startChainPoll: vi.fn((tick: () => void | Promise<void>, opts?: { runImmediately?: boolean }) => {
    const stop = vi.fn()
    pollState.stops.push(stop)
    pollState.ticks.push(async () => {
      await tick()
    })
    // dashboard 使用 runImmediately: false，不要自动跑
    if (opts?.runImmediately !== false) {
      void tick()
    }
    return {
      get active() {
        return stop.mock.calls.length === 0
      },
      stop,
    }
  }),
}))

import { useDashboardData } from '../composables/useDashboardData'
import { useAuthStore } from '../stores/auth'
import { startChainPoll } from '../lib/chain-poll'

describe('useDashboardData (mount + SSE + poll)', () => {
  const today = new Date().toISOString().split('T')[0]
  let OriginalEventSource: typeof EventSource | undefined

  beforeEach(() => {
    toastSpy.success.mockClear()
    toastSpy.error.mockClear()
    notifyApiErrorSpy.mockClear()
    pollState.ticks.length = 0
    pollState.stops.length = 0
    MockEventSource.reset()
    vi.mocked(startChainPoll).mockClear()

    for (const fn of Object.values(api)) {
      fn.mockReset()
    }
    activeRunsStoreMock.runs.value = []
    activeRunsStoreMock.refresh.mockClear()
    activeRunsStoreMock.ensurePolling.mockClear()
    activeRunsStoreMock.acquire.mockClear()
    activeRunsStoreMock.release.mockClear()

    OriginalEventSource = globalThis.EventSource
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource

    useAuthStore().setToken('tok')

    api.listAccounts.mockResolvedValue({
      accounts: [
        { name: 'a1', status: 'connected' },
        { name: 'a2', status: 'checking' },
        { name: 'a3', status: 'invalid' },
      ],
      total: 3,
    })
    api.listSignTasks.mockResolvedValue([{ name: 't1' }, { name: 't2' }])
    api.getRecentAccountLogs.mockResolvedValue([
      {
        account_name: 'a1',
        task_name: 't1',
        success: true,
        created_at: `${today}T01:00:00`,
        message: 'ok',
      },
      {
        account_name: 'a2',
        task_name: 't2',
        success: false,
        created_at: `${today}T02:00:00`,
        message: 'fail',
        failure_category: 'timeout',
      },
    ])
    api.listScheduledJobs.mockResolvedValue({
      jobs: [
        { id: 'j1', kind: 'sign', next_run_time: '2026-07-02T00:00:00' },
        { id: 'sys', kind: 'system', next_run_time: '2026-07-02T00:00:00' },
      ],
    })
    api.listActiveSignTaskRuns.mockResolvedValue({
      runs: [{ task_name: 't1', state: 'running' }],
    })
    api.listKeywordHits.mockResolvedValue({ items: [{ id: 1, keyword: 'k' }] })
    api.listAccountStatusCheckJobs.mockResolvedValue({
      jobs: [{ job_id: 'job1', status: 'running', progress: { done: 1, total: 2 } }],
    })
  })

  afterEach(() => {
    if (OriginalEventSource) {
      globalThis.EventSource = OriginalEventSource
    } else {
      // @ts-expect-error cleanup
      delete globalThis.EventSource
    }
    vi.useRealTimers()
  })

  it('loads stats/logs/jobs on mount and starts poll + SSE', async () => {
    const { result, unmount } = mountComposable(() => useDashboardData())
    await vi.waitFor(() => {
      expect(result.pageLoading.value).toBe(false)
    })
    await flushPromises(10)

    const statsMap = Object.fromEntries(result.stats.value.map((s) => [s.key, s.value]))
    expect(statsMap['dashboard.activeAccounts']).toBe('2/3')
    expect(statsMap['dashboard.totalTasks']).toBe('2')
    expect(statsMap['dashboard.recentSuccess']).toBe('1')
    expect(statsMap['dashboard.recentFailure']).toBe('1')
    expect(result.logs.value).toHaveLength(2)
    expect(result.upcomingJobs.value).toHaveLength(1)
    expect(result.upcomingJobs.value[0].id).toBe('j1')
    expect(result.activeRuns.value).toHaveLength(1)
    expect(result.failureBreakdown.value.some((x) => x.category === 'timeout')).toBe(true)
    expect(result.recentHits.value).toHaveLength(1)
    expect(result.statusJobs.value[0].job_id).toBe('job1')

    expect(startChainPoll).toHaveBeenCalled()
    expect(MockEventSource.instances.length).toBeGreaterThanOrEqual(1)
    expect(MockEventSource.instances[0].url).toContain('/api/events/sign-history?token=tok')

    unmount()
    expect(pollState.stops[0]).toHaveBeenCalled()
  })

  it('uses a Dashboard-specific fallback when an initial data source fails', async () => {
    api.getRecentAccountLogs.mockRejectedValueOnce(new Error('logs unavailable'))
    const { result, unmount } = mountComposable(() => useDashboardData())
    try {
      await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))

      expect(notifyApiErrorSpy).toHaveBeenCalledWith(
        expect.any(Error),
        'dashboard.loadFailed',
      )
    } finally {
      unmount()
    }
  })

  it('exposes partial load state while keeping successful dashboard data visible', async () => {
    api.listScheduledJobs.mockRejectedValueOnce(new Error('schedule unavailable'))
    const { result, unmount } = mountComposable(() => useDashboardData())
    try {
      await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))

      expect(result.partialLoad.value).toBe(true)
      expect(result.stats.value.find((s) => s.key === 'dashboard.totalTasks')?.value).toBe('2')

      await pollState.ticks[0]()
      await flushPromises(10)

      expect(result.partialLoad.value).toBe(false)
    } finally {
      unmount()
    }
  })

  it('marks partial load when the shared active-runs refresh reports failure', async () => {
    activeRunsStoreMock.refresh.mockResolvedValueOnce(false)
    const { result, unmount } = mountComposable(() => useDashboardData())
    try {
      await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))

      expect(result.partialLoad.value).toBe(true)
      expect(result.stats.value.find((s) => s.key === 'dashboard.totalTasks')?.value).toBe('2')
    } finally {
      unmount()
    }
  })

  it('SSE ready/sign_log updates live state and prepends log', async () => {
    const { result, unmount } = mountComposable(() => useDashboardData())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    await vi.waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0))

    const es = MockEventSource.instances[0]
    es.emit('ready', {})
    expect(result.liveConnected.value).toBe(true)

    es.emit('sign_log', {
      account_name: 'live',
      task_name: 'live-task',
      success: true,
      message: 'from-sse',
      created_at: `${today}T03:00:00`,
    })
    expect(result.logs.value[0].account).toBe('live')
    expect(result.logs.value[0].text).toBe('from-sse')
    unmount()
  })

  it('SSE error schedules reconnect with backoff', async () => {
    vi.useFakeTimers()
    const { result, unmount } = mountComposable(() => useDashboardData())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    await vi.waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0))
    const before = MockEventSource.instances.length

    MockEventSource.instances[0].triggerError()
    expect(result.liveConnected.value).toBe(false)

    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises(10)
    expect(MockEventSource.instances.length).toBeGreaterThan(before)
    unmount()
  })

  it('refresh poll tick reloads data without flipping pageLoading', async () => {
    const { result, unmount } = mountComposable(() => useDashboardData())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    await vi.waitFor(() => expect(pollState.ticks.length).toBe(1))

    api.listSignTasks.mockResolvedValue([{ name: 't1' }, { name: 't2' }, { name: 't3' }])
    await pollState.ticks[0]()
    await flushPromises(10)

    const tasksStat = result.stats.value.find((s) => s.key === 'dashboard.totalTasks')
    expect(tasksStat?.value).toBe('3')
    expect(result.pageLoading.value).toBe(false)
    unmount()
  })

  it('pauses 30s poll while tab hidden and refreshes immediately on visible', async () => {
    const hiddenDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'hidden')
    const visibilityDesc = Object.getOwnPropertyDescriptor(
      Document.prototype,
      'visibilityState',
    )

    const { result, unmount } = mountComposable(() => useDashboardData())
    await vi.waitFor(() => expect(result.pageLoading.value).toBe(false))
    await vi.waitFor(() => expect(pollState.ticks.length).toBe(1))

    // 隐藏标签页：停止轮询，不再续约
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(pollState.stops[0]).toHaveBeenCalled()

    // 回到前台：立即刷新一次并重建轮询
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    api.listSignTasks.mockResolvedValue([{ name: 't1' }, { name: 't2' }, { name: 't3' }])
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises(10)

    expect(startChainPoll).toHaveBeenCalledTimes(2)
    const tasksStat = result.stats.value.find((s) => s.key === 'dashboard.totalTasks')
    expect(tasksStat?.value).toBe('3')

    if (hiddenDesc) Object.defineProperty(document, 'hidden', hiddenDesc)
    if (visibilityDesc) Object.defineProperty(document, 'visibilityState', visibilityDesc)
    unmount()
  })
})
