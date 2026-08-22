import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'

const { toastSpy, confirmMock, api, pollState } = vi.hoisted(() => ({
  toastSpy: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    show: vi.fn(),
  },
  confirmMock: {
    confirm: vi.fn(async () => true),
  },
  api: {
    listKeywordHits: vi.fn(),
    listKeywordHitGroups: vi.fn(),
    exportKeywordHitsBlob: vi.fn(),
    clearKeywordHits: vi.fn(),
  },
  pollState: { lastCb: null as null | (() => Promise<void>) },
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
vi.mock('../lib/api', () => api)

vi.mock('../lib/download', () => ({
  downloadBlob: vi.fn(),
}))

vi.mock('../lib/chain-poll', () => ({
  startChainPoll: vi.fn((cb: () => Promise<void>) => {
    // 记录回调供测试直接驱动（模拟轮询 tick）
    pollState.lastCb = cb
    return { stop: vi.fn(), active: true }
  }),
}))

import { useTaskHits } from '../composables/useTaskHits'
import { useAuthStore } from '../stores/auth'
import { startChainPoll } from '../lib/chain-poll'
import { downloadBlob } from '../lib/download'

describe('useTaskHits', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore().setToken('tok')
    confirmMock.confirm.mockResolvedValue(true)
  })

  function setup(opts?: { taskName?: string; isListen?: boolean; isOpen?: boolean }) {
    const panelTab = ref<'history' | 'hits'>('hits')
    return useTaskHits({
      taskName: computed(() => opts?.taskName ?? 'listen-task'),
      accountName: computed(() => 'acc1'),
      isListenTask: computed(() => opts?.isListen ?? true),
      isOpen: computed(() => opts?.isOpen ?? true),
      panelTab,
    })
  }

  it('loadHits fills list and total', async () => {
    api.listKeywordHits.mockResolvedValue({
      items: [
        { id: 1, keyword: 'k', time: 't', message_text: 'm' },
        { id: 2, keyword: 'k2', time: 't2', message_text: 'm2' },
      ],
      total: 2,
    })
    const hits = setup()
    await hits.loadHits()
    expect(hits.hitRecords.value).toHaveLength(2)
    expect(hits.hitTotal.value).toBe(2)
    expect(hits.canLoadMoreHits.value).toBe(false)
    expect(api.listKeywordHits).toHaveBeenCalledWith(
      'tok',
      expect.objectContaining({ task_name: 'listen-task', account_name: 'acc1', limit: 50, offset: 0 }),
    )
  })

  it('loadHits no-ops without task name', async () => {
    const hits = setup({ taskName: '' })
    await hits.loadHits()
    expect(api.listKeywordHits).not.toHaveBeenCalled()
  })

  it('loadHits groups mode', async () => {
    api.listKeywordHitGroups.mockResolvedValue({
      groups: [
        { key: 'c1', label: 'chat', count: 3, items: [] },
        { key: 'c2', label: 'chat2', count: 1, items: [] },
      ],
    })
    const hits = setup()
    hits.hitsView.value = 'groups'
    await hits.loadHits()
    expect(hits.hitGroups.value).toHaveLength(2)
    expect(hits.hitTotal.value).toBe(4)
    expect(hits.hitRecords.value).toEqual([])
  })

  it('loadMoreHits appends without duplicates', async () => {
    api.listKeywordHits
      .mockResolvedValueOnce({
        items: [{ id: 1, keyword: 'a', time: 't', message_text: '' }],
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [
          { id: 1, keyword: 'a', time: 't', message_text: '' },
          { id: 2, keyword: 'b', time: 't', message_text: '' },
        ],
        total: 3,
      })
    const hits = setup()
    await hits.loadHits()
    expect(hits.canLoadMoreHits.value).toBe(true)
    await hits.loadMoreHits()
    expect(hits.hitRecords.value.map((h) => h.id)).toEqual([1, 2])
  })

  it('resetHitsState clears and stops poll', () => {
    const hits = setup()
    hits.hitRecords.value = [{ id: 1 } as never]
    hits.hitTotal.value = 9
    hits.hitsView.value = 'groups'
    hits.ensureHitsAutoRefresh()
    expect(startChainPoll).toHaveBeenCalled()
    hits.resetHitsState()
    expect(hits.hitRecords.value).toEqual([])
    expect(hits.hitTotal.value).toBe(0)
    expect(hits.hitsView.value).toBe('list')
  })

  it('auto-refresh tick skips requests while tab hidden', async () => {
    api.listKeywordHits.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 })
    const hits = setup()
    hits.ensureHitsAutoRefresh()
    expect(pollState.lastCb).toBeTruthy()

    // 隐藏时 tick 不请求
    Object.defineProperty(document, 'hidden', { value: true, configurable: true })
    await pollState.lastCb!()
    expect(api.listKeywordHits).not.toHaveBeenCalled()

    // 恢复可见后正常请求
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    await pollState.lastCb!()
    expect(api.listKeywordHits).toHaveBeenCalled()
    Object.defineProperty(document, 'hidden', { value: false, configurable: true })
  })

  it('clearHits confirms then clears', async () => {
    api.clearKeywordHits.mockResolvedValue({ deleted: 4 })
    api.listKeywordHits.mockResolvedValue({ items: [], total: 0 })
    const hits = setup()
    await hits.clearHits()
    expect(confirmMock.confirm).toHaveBeenCalled()
    expect(api.clearKeywordHits).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('clearHits aborts when confirm false', async () => {
    confirmMock.confirm.mockResolvedValueOnce(false)
    const hits = setup()
    await hits.clearHits()
    expect(api.clearKeywordHits).not.toHaveBeenCalled()
  })

  it('loadHits surfaces errors', async () => {
    api.listKeywordHits.mockRejectedValue(new Error('net'))
    const hits = setup()
    await hits.loadHits()
    expect(toastSpy.error).toHaveBeenCalled()
    expect(hits.hitRecords.value).toEqual([])
  })

  it('exportHits downloads blob with limit 2000 and resets busy', async () => {
    api.exportKeywordHitsBlob.mockResolvedValue(new Blob(['csv']))
    const hits = setup()
    await hits.exportHits()
    expect(api.exportKeywordHitsBlob).toHaveBeenCalledWith(
      'tok',
      expect.objectContaining({ task_name: 'listen-task', account_name: 'acc1', limit: 2000 }),
    )
    expect(downloadBlob).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
    expect(hits.hitsExporting.value).toBe(false)
  })

  it('exportHits no-ops without task name and surfaces errors', async () => {
    const hits = setup({ taskName: '' })
    await hits.exportHits()
    expect(api.exportKeywordHitsBlob).not.toHaveBeenCalled()

    api.exportKeywordHitsBlob.mockRejectedValue(new Error('boom'))
    const hits2 = setup()
    await hits2.exportHits()
    expect(toastSpy.error).toHaveBeenCalled()
    expect(hits2.hitsExporting.value).toBe(false)
  })

  it('exportHits ignores duplicate calls while in flight', async () => {
    let resolveExport!: (v: Blob) => void
    api.exportKeywordHitsBlob.mockReturnValueOnce(
      new Promise<Blob>((resolve) => { resolveExport = resolve }),
    )
    const hits = setup()
    const p1 = hits.exportHits()
    const p2 = hits.exportHits() // 在途时二次调用应被短路
    resolveExport(new Blob(['x']))
    await Promise.all([p1, p2])
    expect(api.exportKeywordHitsBlob).toHaveBeenCalledTimes(1)
  })

  it('clearHits ignores duplicate calls while clearing', async () => {
    let resolveClear!: (v: { deleted: number }) => void
    api.clearKeywordHits.mockReturnValueOnce(
      new Promise<{ deleted: number }>((resolve) => { resolveClear = resolve }),
    )
    api.listKeywordHits.mockResolvedValue({ items: [], total: 0 })
    const hits = setup()
    const p1 = hits.clearHits()
    const p2 = hits.clearHits() // 清空请求在途时二次调用应被短路
    resolveClear({ deleted: 3 })
    await Promise.all([p1, p2])
    expect(api.clearKeywordHits).toHaveBeenCalledTimes(1)
    // 清空成功后刷新列表计数
    expect(api.listKeywordHits).toHaveBeenCalled()
    expect(hits.hitsClearing.value).toBe(false)
  })
})
