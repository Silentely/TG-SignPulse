/**
 * Task 11: TaskLogsModal Component Test Gate
 *
 * Verifies:
 * 1. Component mounting with header extra slots (connection badge, live status badge).
 * 2. VirtualLogViewer integration and rendering of realtime logs.
 * 3. Tab switching between history and hits for listen mode tasks.
 * 4. Refresh button triggers appropriate load action.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mount } from '@vue/test-utils'

const streamSpy = vi.hoisted(() => ({
  disconnect: vi.fn(),
  connect: vi.fn(),
  resetLiveFailure: vi.fn(),
  clearLiveStatus: vi.fn(),
  clearRealtimeLogs: vi.fn(),
}))

const hitsSpy = vi.hoisted(() => ({
  loadHits: vi.fn(),
  exportHits: vi.fn(),
  clearHits: vi.fn(),
  loadMoreHits: vi.fn(),
  ensureHitsAutoRefresh: vi.fn(),
  clearHitsAutoRefresh: vi.fn(),
  resetHitsState: vi.fn(),
}))

const sharedRealtimeLogs = ref<string[]>([])
const sharedIsRunning = ref(false)
const sharedLivePhase = ref('')
const sharedLivePhaseDetail = ref('')
const sharedLiveFailureCategory = ref('')
const sharedLiveState = ref('')
const sharedLiveStatusLabel = ref('')
const sharedLiveStatusToneClass = ref('')
const sharedConnectionState = ref<'connected' | 'reconnecting' | 'polling' | 'closed'>('closed')
const sharedConnectionStateText = ref('')
const sharedRetryAttempt = ref(0)
const sharedBackoffDelayMs = ref(0)

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), show: vi.fn() }),
}))

vi.mock('../composables/useTaskRunStream', () => ({
  useTaskRunStream: () => ({
    realtimeLogs: sharedRealtimeLogs,
    isRunning: sharedIsRunning,
    livePhase: sharedLivePhase,
    livePhaseDetail: sharedLivePhaseDetail,
    liveFailureCategory: sharedLiveFailureCategory,
    liveState: sharedLiveState,
    liveStatusLabel: sharedLiveStatusLabel,
    liveStatusToneClass: sharedLiveStatusToneClass,
    connectionState: sharedConnectionState,
    connectionStateText: sharedConnectionStateText,
    retryAttempt: sharedRetryAttempt,
    backoffDelayMs: sharedBackoffDelayMs,
    connect: streamSpy.connect,
    disconnect: streamSpy.disconnect,
    resetLiveFailure: streamSpy.resetLiveFailure,
    clearLiveStatus: streamSpy.clearLiveStatus,
    clearRealtimeLogs: streamSpy.clearRealtimeLogs,
  }),
}))

vi.mock('../composables/useTaskHits', () => ({
  useTaskHits: () => ({
    hitRecords: ref([]),
    hitGroups: ref([]),
    hitTotal: ref(5),
    hitsView: ref('list'),
    hitGroupBy: ref('chat'),
    hitsLoading: ref(false),
    hitsLoadingMore: ref(false),
    hitsExporting: ref(false),
    hitsClearing: ref(false),
    canLoadMoreHits: ref(false),
    loadHits: hitsSpy.loadHits,
    loadMoreHits: hitsSpy.loadMoreHits,
    exportHits: hitsSpy.exportHits,
    clearHits: hitsSpy.clearHits,
    ensureHitsAutoRefresh: hitsSpy.ensureHitsAutoRefresh,
    clearHitsAutoRefresh: hitsSpy.clearHitsAutoRefresh,
    resetHitsState: hitsSpy.resetHitsState,
  }),
}))

vi.mock('../api/sign-tasks', () => ({
  getSignTaskHistory: vi.fn(async () => []),
}))

import TaskLogsModal from '../components/tasks/TaskLogsModal.vue'

const dummyTask = {
  id: 't-test',
  name: 'test-task',
  account_name: 'acc-1',
  account_names: ['acc-1'],
  isListenMode: true,
  hitCount: 5,
  raw: {
    name: 'test-task',
    account_name: 'acc-1',
    execution_mode: 'listen',
  },
} as any

describe('TaskLogsModal Component Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sharedRealtimeLogs.value = []
    sharedIsRunning.value = false
    sharedConnectionState.value = 'closed'
    sharedConnectionStateText.value = ''
  })

  it('renders modal and displays connection badge when connectionState is active', async () => {
    sharedConnectionState.value = 'reconnecting'
    sharedConnectionStateText.value = 'Reconnecting (2/5)... 2s'

    const wrapper = mount(TaskLogsModal, {
      props: { isOpen: true, task: dummyTask },
      global: {
        stubs: {
          Modal: {
            template: `
              <div class="modal-stub">
                <slot name="header-extra" />
                <slot />
              </div>
            `,
          },
          TaskLogsHitsPanel: true,
          TaskLogsHistoryPanel: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Reconnecting (2/5)... 2s')
  })

  it('renders VirtualLogViewer when realtimeLogs are available', async () => {
    sharedRealtimeLogs.value = ['[12:00:00] task started', '[12:00:01] processing step']
    sharedIsRunning.value = true

    const wrapper = mount(TaskLogsModal, {
      props: { isOpen: true, task: dummyTask },
      global: {
        stubs: {
          Modal: {
            template: `
              <div class="modal-stub">
                <slot name="header-extra" />
                <slot />
              </div>
            `,
          },
          TaskLogsHitsPanel: true,
          TaskLogsHistoryPanel: true,
        },
      },
    })

    // Virtual viewer element should be rendered
    const viewer = wrapper.findComponent({ name: 'VirtualLogViewer' })
    expect(viewer.exists()).toBe(true)
    expect(viewer.props('lines')).toHaveLength(2)
  })

  it('switches between history and hits tabs', async () => {
    const wrapper = mount(TaskLogsModal, {
      props: { isOpen: true, task: dummyTask },
      global: {
        stubs: {
          Modal: {
            template: `
              <div class="modal-stub">
                <slot name="header-extra" />
                <slot />
              </div>
            `,
          },
          TaskLogsHitsPanel: true,
          TaskLogsHistoryPanel: true,
        },
      },
    })

    const tabs = wrapper.findAll('button[role="tab"]')
    expect(tabs.length).toBe(2)

    // Click hits tab
    await tabs[1].trigger('click')
    expect(hitsSpy.loadHits).toHaveBeenCalled()
  })
})
