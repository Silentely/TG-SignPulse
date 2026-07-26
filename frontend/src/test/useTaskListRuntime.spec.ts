import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import {
  flushPromises,
  makeTaskUi,
  mockI18nPassthrough,
  mountComposable,
} from './composable-test-utils'

const toastSpy = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  show: vi.fn(),
}))

const api = vi.hoisted(() => ({
  listActiveSignTaskRuns: vi.fn(),
  cancelSignTaskRun: vi.fn(),
  listKeywordHitGroups: vi.fn(),
  fetchChatAvatar: vi.fn(),
  listAccounts: vi.fn(),
}))

const pollHandles = vi.hoisted(() => [] as Array<{ stop: ReturnType<typeof vi.fn>; tick: () => Promise<void>; intervalMs: number }>)

const activeRunsStoreMock = vi.hoisted(() => {
  const byTask = { value: {} as Record<string, unknown[]> }
  const fetchedAt = { value: 0 }
  const hasAnyActive = { value: false }
  const store = {
    byTask,
    fetchedAt,
    hasAnyActive,
    runs: { value: [] as unknown[] },
    refresh: vi.fn(async () => {
      const res = await api.listActiveSignTaskRuns('tok')
      const runs = res?.runs || []
      store.runs.value = runs
      const grouped: Record<string, unknown[]> = {}
      for (const r of runs) {
        const key = String((r as { task_name?: string }).task_name || '')
        if (!grouped[key]) grouped[key] = []
        grouped[key].push(r)
      }
      byTask.value = grouped
      fetchedAt.value = Date.now()
      hasAnyActive.value = runs.some((r: { state?: string }) => r.state === 'running')
    }),
    seedFromTaskActiveRuns: vi.fn((flat: unknown[]) => {
      store.runs.value = flat
      const grouped: Record<string, unknown[]> = {}
      for (const r of flat as Array<{ task_name?: string }>) {
        const key = String(r.task_name || '')
        if (!grouped[key]) grouped[key] = []
        grouped[key].push(r)
      }
      byTask.value = grouped
      fetchedAt.value = Date.now()
      hasAnyActive.value = flat.length > 0
    }),
    ensurePolling: vi.fn(() => {
      if (hasAnyActive.value && !pollHandles.some((h) => h.intervalMs === 4000 && !h.stop.mock.calls.length)) {
        // 模拟 store 内 4s 轮询
        const tick = async () => {
          await store.refresh()
        }
        const handle = {
          stop: vi.fn(),
          tick,
          intervalMs: 4000,
          get active() {
            return !handle.stop.mock.calls.length
          },
        }
        pollHandles.push(handle)
      }
    }),
    acquire: vi.fn(),
    release: vi.fn(),
  }
  return store
})

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
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
  startChainPoll: vi.fn((tick: () => Promise<void>, opts?: { intervalMs?: number; runImmediately?: boolean }) => {
    const handle = {
      stop: vi.fn(),
      tick,
      intervalMs: opts?.intervalMs ?? 0,
      get active() {
        return !handle.stop.mock.calls.length
      },
    }
    pollHandles.push(handle)
    if (opts?.runImmediately !== false) void tick()
    return handle
  }),
}))

import { useTaskListRuntime } from '../composables/useTaskListRuntime'
import { useAuthStore } from '../stores/auth'
import { startChainPoll } from '../lib/chain-poll'

describe('useTaskListRuntime (poll + cancel)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pollHandles.length = 0
    activeRunsStoreMock.byTask.value = {}
    activeRunsStoreMock.runs.value = []
    activeRunsStoreMock.hasAnyActive.value = false
    activeRunsStoreMock.fetchedAt.value = 0
    useAuthStore().setToken('tok')
    api.listActiveSignTaskRuns.mockResolvedValue({ runs: [] })
    api.listKeywordHitGroups.mockResolvedValue({ groups: [] })
    api.listAccounts.mockResolvedValue({
      accounts: [
        { name: 'acc1', status: 'connected', needs_relogin: false },
        { name: 'bad', status: 'invalid', needs_relogin: true },
      ],
    })
    api.cancelSignTaskRun.mockResolvedValue({ ok: true, cancelled: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function setup(tasks = [
    makeTaskUi({
      name: 'listen-1',
      id: 'listen-1',
      isListenMode: true,
      raw: {
        name: 'listen-1',
        account_name: 'acc1',
        account_names: ['acc1'],
        execution_mode: 'listen',
        chats: [{ chat_id: 11, name: 'c', source_account: 'acc1' }],
        active_run: {
          task_name: 'listen-1',
          account_name: 'acc1',
          run_id: 'r1',
          state: 'running',
          phase: 'running',
        },
      },
    }),
    makeTaskUi({
      name: 'sched-1',
      id: 'sched-1',
      raw: {
        name: 'sched-1',
        account_name: 'bad',
        account_names: ['bad'],
      },
    }),
  ]) {
    const tasksRef = ref(tasks)
    const harness = mountComposable(() =>
      useTaskListRuntime({
        tasks: tasksRef,
        listenTaskCount: computed(() => tasksRef.value.filter((t) => t.isListenMode).length),
        accountFilter: computed(() => ''),
        getTaskAccountName: (t) => {
          const raw = 'raw' in t ? t.raw : t
          return String(raw.account_name || '')
        },
      }),
    )
    return { ...harness, tasksRef }
  }

  it('afterTasksLoaded syncs active runs and starts polls', async () => {
    const { result, tasksRef, unmount } = setup()
    await result.afterTasksLoaded()
    await flushPromises()

    expect(result.taskActiveRun(tasksRef.value[0])?.run_id).toBe('r1')
    expect(startChainPoll).toHaveBeenCalled()
    // active run poll + hit count poll
    expect(pollHandles.length).toBeGreaterThanOrEqual(1)
    expect(api.listKeywordHitGroups).toHaveBeenCalled()
    unmount()
    // onUnmounted: hit-count poll stop + store release
    expect(activeRunsStoreMock.release).toHaveBeenCalled()
    expect(pollHandles.filter((h) => h.intervalMs === 15000).every((h) => h.stop.mock.calls.length > 0)).toBe(true)
  })

  it('loadAccountStatusMap + taskHasInvalidAccount', async () => {
    const { result, tasksRef, unmount } = setup()
    await result.loadAccountStatusMap()
    expect(result.taskHasInvalidAccount(tasksRef.value[1])).toBe(true)
    expect(result.taskHasInvalidAccount(tasksRef.value[0])).toBe(false)
    unmount()
  })

  it('handleCancelRun success refreshes runs', async () => {
    api.listActiveSignTaskRuns.mockResolvedValue({ runs: [] })
    const { result, tasksRef, unmount } = setup()
    await result.afterTasksLoaded()
    await result.handleCancelRun(tasksRef.value[0])
    expect(api.cancelSignTaskRun).toHaveBeenCalledWith('tok', 'listen-1', 'acc1', 'r1')
    expect(toastSpy.success).toHaveBeenCalled()
    expect(api.listActiveSignTaskRuns).toHaveBeenCalled()
    unmount()
  })

  it('handleCancelRun surfaces failure', async () => {
    api.cancelSignTaskRun.mockResolvedValue({ ok: false, cancelled: false, error: 'busy' })
    const { result, tasksRef, unmount } = setup()
    await result.afterTasksLoaded()
    await result.handleCancelRun(tasksRef.value[0])
    expect(toastSpy.error).toHaveBeenCalled()
    unmount()
  })

  it('refreshActiveRuns via poll tick', async () => {
    const { result, unmount } = setup()
    await result.afterTasksLoaded()
    await flushPromises()
    api.listActiveSignTaskRuns.mockResolvedValue({
      runs: [
        {
          task_name: 'listen-1',
          account_name: 'acc1',
          run_id: 'r2',
          state: 'running',
          phase: 'cooldown',
        },
      ],
    })
    // find active poll (interval 4000)
    const activePoll = pollHandles.find((h) => h.intervalMs === 4000)
    expect(activePoll).toBeTruthy()
    await activePoll!.tick()
    await flushPromises()
    unmount()
  })

  it('hit count poll updates listen task hitCount', async () => {
    api.listKeywordHitGroups.mockResolvedValue({
      groups: [{ key: 'listen-1', count: 7, label: 'listen-1', items: [] }],
    })
    const { result, tasksRef, unmount } = setup()
    await result.loadListenHitCounts()
    expect(tasksRef.value[0].hitCount).toBe(7)
    unmount()
  })
})
