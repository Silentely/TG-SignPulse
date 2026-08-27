/**
 * TaskLogsModal 卸载清理回归：弹窗开着时组件被卸载，
 * 必须停掉 WS、命中轮询与在途日志响应，防止连接与定时器泄漏。
 */
import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

const streamSpy = vi.hoisted(() => ({
  disconnect: vi.fn(),
  connect: vi.fn(),
}))
const hitsSpy = vi.hoisted(() => ({
  resetHitsState: vi.fn(),
}))
const guardSpy = vi.hoisted(() => ({
  invalidate: vi.fn(),
  next: vi.fn(() => 1),
  isCurrent: vi.fn(() => true),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), show: vi.fn() }),
}))
vi.mock('../composables/useTaskRunStream', () => ({
  useTaskRunStream: () => ({
    realtimeLogs: ref([]),
    livePhase: ref(''),
    livePhaseDetail: ref(''),
    liveFailureCategory: ref(''),
    liveState: ref(''),
    liveStatusLabel: ref(''),
    liveStatusToneClass: ref(''),
    connect: streamSpy.connect,
    disconnect: streamSpy.disconnect,
    resetLiveFailure: vi.fn(),
    clearLiveStatus: vi.fn(),
    clearRealtimeLogs: vi.fn(),
  }),
}))
vi.mock('../composables/useTaskHits', () => ({
  useTaskHits: () => ({
    hitRecords: ref([]),
    hitGroups: ref([]),
    hitTotal: ref(0),
    hitsView: ref('list'),
    hitGroupBy: ref('chat'),
    hitsLoading: ref(false),
    loadHits: vi.fn(),
    ensureHitsAutoRefresh: vi.fn(),
    clearHitsAutoRefresh: vi.fn(),
    resetHitsState: hitsSpy.resetHitsState,
    exportHits: vi.fn(),
  }),
}))
vi.mock('../lib/latest-response', () => ({
  useLatestResponseGuard: () => guardSpy,
}))

import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'

const task = {
  id: 't1',
  name: 'listen-1',
  account_name: 'acc1',
  account_names: ['acc1'],
  isListenMode: true,
  hitCount: 0,
  raw: {
    name: 'listen-1',
    account_name: 'acc1',
    account_names: ['acc1'],
    execution_mode: 'listen',
    chats: [],
  },
} as never

describe('TaskLogsModal 卸载清理', () => {
  it('打开状态卸载时断开 WS、重置命中并使在途响应失效', () => {
    const wrapper = mount(TaskLogsModal, {
      props: { isOpen: true, task, runAccount: '' },
      global: {
        stubs: {
          Modal: { template: '<div><slot /><slot name="footer" /></div>' },
          TaskLogsHitsPanel: true,
          TaskLogsHistoryPanel: true,
        },
      },
    })
    wrapper.unmount()
    expect(guardSpy.invalidate).toHaveBeenCalled()
    expect(hitsSpy.resetHitsState).toHaveBeenCalled()
    expect(streamSpy.disconnect).toHaveBeenCalled()
  })
})
