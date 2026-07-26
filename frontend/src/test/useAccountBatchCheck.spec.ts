import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import {
  flushPromises,
  makeAccountUi,
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
  checkAccountsStatus: vi.fn(),
  startAccountStatusCheckJob: vi.fn(),
  getAccountStatusCheckJob: vi.fn(),
  listAccountStatusCheckJobs: vi.fn(),
  cancelAccountStatusCheckJob: vi.fn(),
}))

const pollTicks = vi.hoisted(() => [] as Array<() => Promise<void>>)
const pollStops = vi.hoisted(() => [] as Array<ReturnType<typeof vi.fn>>)

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
}))
vi.mock('../lib/api', () => api)
vi.mock('../lib/chain-poll', () => ({
  startChainPoll: vi.fn((tick: () => Promise<void>) => {
    const stop = vi.fn()
    pollStops.push(stop)
    pollTicks.push(tick)
    // 不立即跑，避免与 start 后的显式 poll 叠两次
    return {
      get active() {
        return stop.mock.calls.length === 0
      },
      stop,
    }
  }),
}))

import { useAccountBatchCheck } from '../composables/useAccountBatchCheck'
import { useAuthStore } from '../stores/auth'

describe('useAccountBatchCheck (job poll)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    pollTicks.length = 0
    pollStops.length = 0
    useAuthStore().setToken('tok')
  })

  function setup(names = ['a1', 'a2']) {
    const accounts = ref(names.map((n) => makeAccountUi(n)))
    const searchQuery = ref('')
    const loadAccounts = vi.fn(async () => {})
    const harness = mountComposable(() =>
      useAccountBatchCheck({
        accounts,
        filteredAccounts: computed(() => accounts.value),
        searchQuery,
        loadAccounts,
      }),
    )
    return { ...harness, accounts, searchQuery, loadAccounts }
  }

  it('single account batch uses sync check API', async () => {
    api.checkAccountsStatus.mockResolvedValue({
      results: [{ account_name: 'only', ok: true, status: 'connected', message: 'ok' }],
    })
    const { result, loadAccounts, unmount } = setup(['only'])
    await result.handleBatchCheck()
    expect(api.checkAccountsStatus).toHaveBeenCalled()
    expect(api.startAccountStatusCheckJob).not.toHaveBeenCalled()
    expect(loadAccounts).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
    expect(result.batchChecking.value).toBe(false)
    unmount()
  })

  it('multi account starts job and polls until finished', async () => {
    api.startAccountStatusCheckJob.mockResolvedValue({
      job_id: 'j1',
      status: 'running',
      progress: { done: 0, total: 2, ok: 0, fail: 0 },
      results: [],
    })
    api.getAccountStatusCheckJob
      .mockResolvedValueOnce({
        job_id: 'j1',
        status: 'running',
        progress: { done: 1, total: 2, ok: 1, fail: 0 },
        results: [{ account_name: 'a1', ok: true, status: 'connected', message: 'ok' }],
      })
      .mockResolvedValueOnce({
        job_id: 'j1',
        status: 'finished',
        progress: { done: 2, total: 2, ok: 1, fail: 1 },
        summary: { ok: 1, fail: 1 },
        results: [
          { account_name: 'a1', ok: true, status: 'connected', message: 'ok' },
          { account_name: 'a2', ok: false, status: 'invalid', message: 'expired', needs_relogin: true },
        ],
      })

    const { result, accounts, loadAccounts, unmount } = setup(['a1', 'a2'])
    const p = result.handleBatchCheck()
    await flushPromises()
    expect(api.startAccountStatusCheckJob).toHaveBeenCalled()
    expect(result.batchChecking.value).toBe(true)
    expect(pollTicks.length).toBe(1)

    // 第一次 start 内已 await poll 一次（running）
    // 再跑一轮 poll 到 finished
    await pollTicks[0]()
    await flushPromises()
    await p
    await flushPromises()

    expect(loadAccounts).toHaveBeenCalled()
    expect(result.lastFailedAccountNames.value).toContain('a2')
    expect(accounts.value.find((a) => a.name === 'a2')?.status).toBe('error')
    expect(result.batchChecking.value).toBe(false)
    unmount()
    expect(pollStops[0]).toHaveBeenCalled()
  })

  it('resumeActiveBatchJob restores running job', async () => {
    api.listAccountStatusCheckJobs.mockResolvedValue({
      jobs: [
        {
          job_id: 'resume-1',
          status: 'running',
          progress: { done: 0, total: 2 },
          results: [],
        },
      ],
    })
    api.getAccountStatusCheckJob.mockResolvedValue({
      job_id: 'resume-1',
      status: 'running',
      progress: { done: 0, total: 2 },
      results: [],
    })
    const { result, unmount } = setup()
    await result.resumeActiveBatchJob()
    await flushPromises()
    expect(result.batchChecking.value).toBe(true)
    expect(result.batchJob.value?.job_id).toBe('resume-1')
    expect(pollTicks.length).toBe(1)
    unmount()
  })

  it('handleCheck updates single account', async () => {
    api.checkAccountsStatus.mockResolvedValue({
      results: [{ account_name: 'a1', ok: false, status: 'invalid', message: 'bad' }],
    })
    const loadAccounts = vi.fn(async () => {})
    const accounts = ref([makeAccountUi('a1')])
    const { result, unmount } = mountComposable(() =>
      useAccountBatchCheck({
        accounts,
        filteredAccounts: computed(() => accounts.value),
        searchQuery: ref(''),
        loadAccounts,
      }),
    )
    await result.handleCheck('a1')
    expect(api.checkAccountsStatus).toHaveBeenCalledWith('tok', { account_names: ['a1'] })
    expect(toastSpy.error).toHaveBeenCalled()
    expect(result.checkingAccount.value).toBe('')
    unmount()
  })

  it('handleCancelBatchCheck cancels job', async () => {
    api.startAccountStatusCheckJob.mockResolvedValue({
      job_id: 'j-cancel',
      status: 'running',
      progress: { done: 0, total: 2 },
      results: [],
    })
    api.getAccountStatusCheckJob.mockResolvedValue({
      job_id: 'j-cancel',
      status: 'running',
      progress: { done: 0, total: 2 },
      results: [],
    })
    api.cancelAccountStatusCheckJob.mockResolvedValue({})
    const { result, unmount } = setup(['a1', 'a2'])
    void result.handleBatchCheck()
    await flushPromises()
    api.getAccountStatusCheckJob.mockResolvedValue({
      job_id: 'j-cancel',
      status: 'canceled',
      progress: { done: 1, total: 2 },
      summary: { ok: 0, fail: 1 },
      results: [],
    })
    await result.handleCancelBatchCheck()
    expect(api.cancelAccountStatusCheckJob).toHaveBeenCalledWith('tok', 'j-cancel')
    unmount()
  })

  it('handleBatchCheck no target toasts error', async () => {
    const { result, unmount } = setup([])
    await result.handleBatchCheck()
    expect(toastSpy.error).toHaveBeenCalled()
    expect(api.startAccountStatusCheckJob).not.toHaveBeenCalled()
    unmount()
  })
})
