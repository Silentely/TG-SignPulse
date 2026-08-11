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
    },
    pollHandles,
    startChainPollMock: vi.fn((cb: () => Promise<void>) => {
      const handle = { stop: vi.fn(() => { handle.active = false }), active: true, cb }
      pollHandles.push(handle)
      return handle
    }),
  }
})
vi.mock('../lib/api', () => api)
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

  it('connect opens websocket with token and account', () => {
    const stream = setup('acc-a')
    stream.connect()
    expect(MockWebSocket.instances).toHaveLength(1)
    const url = MockWebSocket.instances[0].url
    expect(url).toContain('/api/sign-tasks/ws/task-a')
    expect(url).toContain('token=tok')
    expect(url).toContain('account_name=acc-a')
    expect(stream.isRunning.value).toBe(true)
    expect(stream.livePhase.value).toBe('starting')
  })

  it('handles logs and done frames', async () => {
    const stream = setup('acc-a')
    stream.connect()
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

  it('disconnect closes socket and clears live phase', () => {
    const stream = setup('acc-a')
    stream.connect()
    stream.disconnect()
    expect(stream.isRunning.value).toBe(false)
    expect(stream.livePhase.value).toBeNull()
  })

  it('falls back to polling on error when runAccount set', async () => {
    api.getSignTaskLogs.mockResolvedValue(['poll-line'])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'running', phase: 'running' })
    const stream = setup('acc-a')
    stream.connect()
    MockWebSocket.instances[0].onerror?.({})
    expect(pollHandles.length).toBeGreaterThan(0)
    await pollHandles[0].cb()
    expect(stream.realtimeLogs.value).toEqual(['poll-line'])
  })

  it('polling stops when status not running', async () => {
    api.getSignTaskLogs.mockResolvedValue([])
    api.getSignTaskRunStatus.mockResolvedValue({ state: 'finished' })
    const stream = setup('acc-a')
    stream.connect()
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
})
