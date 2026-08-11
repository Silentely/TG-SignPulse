import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import { mockI18nPassthrough } from './composable-test-utils'

const { toastSpy, confirmMock, api } = vi.hoisted(() => ({
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

vi.mock('../lib/chain-poll', () => ({
  startChainPoll: vi.fn(() => ({ stop: vi.fn(), active: true })),
}))

import { useTaskHits } from '../composables/useTaskHits'
import { useAuthStore } from '../stores/auth'
import { startChainPoll } from '../lib/chain-poll'

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
})
