import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, nextTick, ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))

const { api, pollHandles, startChainPollMock } = vi.hoisted(() => {
  const pollHandles: Array<{ stop: ReturnType<typeof vi.fn>; active: boolean; cb: () => Promise<void> }> = []
  return {
    api: {
      getSignTaskLogs: vi.fn(),
      getSignTaskRunStatus: vi.fn(),
      issueStreamTicket: vi.fn(),
    },
    pollHandles,
    startChainPollMock: vi.fn((cb: () => Promise<void>) => {
      const handle = { stop: vi.fn(() => { handle.active = false }), active: true, cb }
      pollHandles.push(handle)
      return handle
    }),
  }
})
vi.mock('../lib/api', () => ({
  ...api,
  STREAM_TICKET_PURPOSE: { signHistorySse: 'sign_history_sse', taskRunWs: 'task_run_ws' },
}))
vi.mock('../lib/chain-poll', () => ({
  startChainPoll: startChainPollMock,
}))

type Handler = ((ev?: unknown) => void) | null

class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  onopen: Handler = null
  onmessage: Handler = null
  onerror: Handler = null
  onclose: Handler = null
  readyState = 1
  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }
  close() {
    this.readyState = 3
    this.onclose?.({})
  }
  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

import { useTaskRunStream } from '../composables/useTaskRunStream'
import { useAuthStore } from '../stores/auth'

describe('useTaskRunStream', () => {
  const OriginalWebSocket = globalThis.WebSocket

  beforeEach(() => {
    vi.clearAllMocks()
    pollHandles.length = 0
    MockWebSocket.instances = []
    // 确保 localStorage 可用（勿用 unstubAllGlobals 清掉 setup polyfill）
    if (!globalThis.localStorage || typeof globalThis.localStorage.getItem !== 'function') {
      const store = new Map<string, string>()
      const memoryStorage = {
        get length() { return store.size },
        clear() { store.clear() },
        getItem(key: string) { return store.has(key) ? store.get(key)! : null },
        key(index: number) { return Array.from(store.keys())[index] ?? null },
        removeItem(key: string) { store.delete(key) },
        setItem(key: string, value: string) { store.set(String(key), String(value)) },
      }
      vi.stubGlobal('localStorage', memoryStorage)
    }
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    api.issueStreamTicket.mockResolvedValue({ ticket: 'tk-1', purpose: 'task_run_ws', expires_in: 60 })
    useAuthStore().setToken('tok')
  })

  afterEach(() => {
    globalThis.WebSocket = OriginalWebSocket
  })

  function setup(runAccount?: string) {
    const logContainer = ref<HTMLElement | null>(null)
    const stream = useTaskRunStream({
      taskName: computed(() => 'task-a'),
      accountName: computed(() => 'acc-a'),
      runAccount: computed(() => runAccount),
      logContainer,
    })
    return stream
  }

  it('connect 用一次性票据建连，URL 里不出现长效 JWT', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    expect(MockWebSocket.instances).toHaveLength(1)
    const url = MockWebSocket.instances[0].url
    expect(url).toContain('/api/sign-tasks/ws/task-a')
    expect(url).toContain('ticket=tk-1')
    expect(url).toContain('account_name=acc-a')
    expect(url).not.toContain('token=')
    // 票据绑定用途与任务名
    expect(api.issueStreamTicket).toHaveBeenCalledWith('task_run_ws', 'task-a')
    expect(stream.isRunning.value).toBe(true)
    expect(stream.livePhase.value).toBe('starting')
  })

  it('handles logs and done frames', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    const ws = MockWebSocket.instances[0]
    ws.emitMessage({
      type: 'logs',
      data: ['line1', 'line2'],
      is_running: true,
      phase: 'running',
      phase_detail: '执行中',
    })
    await nextTick()
    expect(stream.realtimeLogs.value).toEqual(['line1', 'line2'])
    expect(stream.livePhaseDetail.value).toBe('执行中')
    expect(stream.liveStatusLabel.value).toBe('执行中')

    ws.emitMessage({ type: 'done', state: 'finished' })
    expect(stream.isRunning.value).toBe(false)
    expect(stream.liveState.value).toBe('finished')
  })

  it('WS 日志行超出上限时截尾，保持有界', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    const ws = MockWebSocket.instances[0]
    // 分多帧推入 1200 行，超出 1000 上限
    for (let i = 0; i < 6; i++) {
      ws.emitMessage({
        type: 'logs',
        data: Array.from({ length: 200 }, (_, j) => `L${i * 200 + j}`),
        is_running: true,
      })
    }
    await nextTick()
    expect(stream.realtimeLogs.value.length).toBe(1000)
    // 保留最新尾部
    expect(stream.realtimeLogs.value[0]).toBe('L200')
    expect(stream.realtimeLogs.value[999]).toBe('L1199')
  })

  it('disconnect closes socket and clears live phase', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    stream.disconnect()
    expect(stream.isRunning.value).toBe(false)
    expect(stream.livePhase.value).toBeNull()
  })

  it('reconnecting closes previous socket and cleans up handlers', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    expect(MockWebSocket.instances).toHaveLength(1)
    const firstSocket = MockWebSocket.instances[0]
    expect(firstSocket.readyState).toBe(1)

    // Second connect should close first socket and clean its handlers
    await stream.connect()
    expect(MockWebSocket.instances).toHaveLength(2)
    expect(firstSocket.readyState).toBe(3)
    expect(firstSocket.onclose).toBeNull()
    expect(firstSocket.onmessage).toBeNull()
  })

  it('disconnect clears socket handlers before closing to prevent ghost polling', async () => {
    const stream = setup('acc-a')
    await stream.connect()
    const ws = MockWebSocket.instances[0]
    stream.disconnect()
    expect(ws.readyState).toBe(3)
    expect(ws.onclose).toBeNull()
    expect(pollHandles).toHaveLength(0)
  })

  it('换票等待期间 disconnect：不得再建连（无孤儿套接字）', async () => {
    let resolveTicket!: (value: unknown) => void
    api.issueStreamTicket.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveTicket = resolve
      }),
    )
    const stream = setup('acc-a')
    const pending = stream.connect()
    // 用户在换票返回前关闭弹窗/离开页面
    stream.disconnect()
    resolveTicket({ ticket: 'tk-late', purpose: 'task_run_ws', expires_in: 60 })
    await pending

    expect(MockWebSocket.instances).toHaveLength(0)
    // 关闭后状态不得被在途 connect 复活
    expect(stream.isRunning.value).toBe(false)
    expect(pollHandles).toHaveLength(0)
  })

  it('连续两次 connect：仅最新一次建连，旧调用弃票', async () => {
    const resolvers: Array<(value: unknown) => void> = []
    api.issueStreamTicket.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve)
        }),
    )
    const stream = setup('acc-a')
    const first = stream.connect()
    const second = stream.connect()
    expect(resolvers).toHaveLength(2)

    // 后发起者先返回，先发起者后返回：后者必须放弃建连
    resolvers[1]({ ticket: 'tk-2', purpose: 'task_run_ws', expires_in: 60 })
    await second
    resolvers[0]({ ticket: 'tk-1', purpose: 'task_run_ws', expires_in: 60 })
    await first

    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toContain('ticket=tk-2')
    expect(MockWebSocket.instances[0].readyState).toBe(1)
  })

  it('换票失败时若已被取代，不接管轮询状态', async () => {
    let rejectTicket!: (reason: unknown) => void
    api.issueStreamTicket.mockReturnValueOnce(
      new Promise((_resolve, reject) => {
        rejectTicket = reject
      }),
    )
    const stream = setup('acc-a')
    const pending = stream.connect()
    stream.disconnect()
    rejectTicket(new Error('401'))
    await pending

    // 旧调用失败不得开启轮询
    expect(pollHandles).toHaveLength(0)
  })

  it('falls back to polling on error when runAccount set', async () => {
    api.getSignTaskLogs.mockResolvedValue(['poll-line'])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'running', phase: 'running' })
    const stream = setup('acc-a')
    await stream.connect()
    MockWebSocket.instances[0].onerror?.({})
    expect(pollHandles.length).toBeGreaterThan(0)
    await pollHandles[0].cb()
    expect(stream.realtimeLogs.value).toEqual(['poll-line'])
  })

  it('polling stops when status not running', async () => {
    api.getSignTaskLogs.mockResolvedValue([])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'finished' })
    const stream = setup('acc-a')
    await stream.connect()
    MockWebSocket.instances[0].onerror?.({})
    const handle = pollHandles[0]
    await handle.cb()
    expect(stream.isRunning.value).toBe(false)
    expect(handle.stop).toHaveBeenCalled()
  })

  it('clear helpers reset failure and logs', () => {
    const stream = setup()
    stream.realtimeLogs.value = ['x']
    stream.liveFailureCategory.value = 'timeout'
    stream.liveState.value = 'running'
    stream.resetLiveFailure()
    stream.clearLiveStatus()
    stream.clearRealtimeLogs()
    expect(stream.liveFailureCategory.value).toBeNull()
    expect(stream.liveState.value).toBeNull()
    expect(stream.realtimeLogs.value).toEqual([])
  })

  it('换票失败时退化为轮询，不建 WebSocket', async () => {
    api.issueStreamTicket.mockRejectedValueOnce(new Error('401'))
    api.getSignTaskLogs.mockResolvedValue(['poll-line'])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'running', phase: 'running' })
    const stream = setup('acc-a')
    await stream.connect()
    expect(MockWebSocket.instances).toHaveLength(0)
    expect(stream.isRunning.value).toBe(false)
    expect(pollHandles).toHaveLength(1)
    await pollHandles[0].cb()
    expect(stream.realtimeLogs.value).toEqual(['poll-line'])
  })

  it('polling skips requests while tab hidden', async () => {
    api.getSignTaskLogs.mockResolvedValue(['hidden-line'])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'running', phase: 'running' })
    const stream = setup('acc-a')
    await stream.connect()
    MockWebSocket.instances[0].onerror?.({})
    const handle = pollHandles[0]

    // 隐藏时 tick 不请求，日志不更新
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    await handle.cb()
    expect(stream.realtimeLogs.value).toEqual([])
    expect(api.getSignTaskLogs).not.toHaveBeenCalled()

    // 恢复可见后正常请求
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    await handle.cb()
    expect(stream.realtimeLogs.value).toEqual(['hidden-line'])
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
  })
})
